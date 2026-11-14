"""Known-set 1v1 adapter for the pinned Foul Play source in vendor/."""
import asyncio
import inspect
import json
import logging
import random
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import sys
from types import SimpleNamespace

from poke_env.player import Player

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor" / "foul-play"))
try:
    from poke_engine import generate_instructions, monte_carlo_tree_search
    from fp.data import all_move_json
    from fp.config import FoulPlayConfig
    from fp.battle import protocol
    from fp.battle.state import Battle, LastUsedMove
    from fp.search.main import select_move_from_mcts_results
    from fp.search.poke_engine_helpers import battle_to_poke_engine_state
    from fp.teams.team_converter import export_to_dict
except ImportError as error:
    raise ImportError("Install search dependencies: python -m pip install -r requirements.txt") from error


# The upstream protocol modifiers, without hidden-set inference. Both private
# requests are available here, so guessing items/spreads from damage is unnecessary.
MODIFIERS = {
    "move": "move", "faint": "faint", "-fail": "fail",
    "-heal": "heal_or_damage", "-damage": "heal_or_damage", "-sethp": "sethp",
    "-setboost": "setboost", "-boost": "boost", "-unboost": "unboost",
    "-status": "status", "-activate": "activate", "-anim": "anim",
    "-prepare": "prepare", "-start": "start_volatile_status",
    "-singlemove": "start_volatile_status", "-end": "end_volatile_status",
    "-curestatus": "curestatus", "-cureteam": "cureteam", "-weather": "weather",
    "-fieldstart": "fieldstart", "-fieldend": "fieldend",
    "-sidestart": "sidestart", "-sideend": "sideend",
    "-swapsideconditions": "swapsideconditions", "-item": "set_item",
    "-enditem": "remove_item", "-immune": "immune", "-ability": "update_ability",
    "detailschange": "form_change", "replace": "illusion_end",
    "-formechange": "form_change", "-transform": "transform", "-mega": "mega",
    "-terastallize": "terastallize", "-clearnegativeboost": "clearnegativeboost",
    "-clearboost": "clearboost", "-clearallboost": "clearallboost",
    "-singleturn": "singleturn", "-mustrecharge": "mustrecharge",
    "upkeep": "upkeep", "cant": "cant", "turn": "turn",
}


class KnownSetsMode:
    """Protocol hooks for a battle with no reserves or disguised opponents."""
    def check_zoroark_from_move(self, battle, side, pokemon, *args):
        return pokemon

    def check_zoroark_from_immune(self, *args):
        pass


def reflected_status_moves(user, opponent):
    """Pure debuffs have no benefit against a known Mirror Armor target."""
    if (opponent.ability.lower() != "mirrorarmor"
            or user.ability.lower() in {"moldbreaker", "teravolt", "turboblaze",
                                        "contrary", "defiant", "competitive"}):
        return set()
    blocked = set()
    for move in user.moves:
        data = all_move_json.get(move.id.lower(), {})
        boosts = data.get("boosts", {})
        if (data.get("category") == "status" and data.get("target") == "normal"
                and boosts and all(amount < 0 for amount in boosts.values())
                and not any(data.get(key) for key in
                            ("self", "selfSwitch", "status", "volatileStatus", "sideCondition"))):
            blocked.add(move.id.lower())
    return blocked


def exclude_reflected_status_moves(state):
    """Apply the same known-ability restriction to both search perspectives."""
    sides = []
    for own, other in ((state.side_one, state.side_two), (state.side_two, state.side_one)):
        active = own.pokemon[int(own.active_index)]
        enemy = other.pokemon[int(other.active_index)]
        blocked = reflected_status_moves(active, enemy)
        # Leave forced choices available when PP/disable leaves no alternative.
        if blocked and any(m.id.lower() not in blocked and m.pp > 0 and not m.disabled
                           and m.id.lower() != "none" for m in active.moves):
            moves = []
            for move in active.moves:
                values = {k: getattr(move, k) for k in inspect.signature(type(move)).parameters}
                if move.id.lower() in blocked:
                    values["disabled"] = True
                moves.append(type(move)(**values))
            values = {k: getattr(active, k) for k in inspect.signature(type(active)).parameters}
            values["moves"] = moves
            pokemon = list(own.pokemon)
            pokemon[int(own.active_index)] = type(active)(**values)
            values = {k: getattr(own, k) for k in inspect.signature(type(own)).parameters}
            values["pokemon"] = pokemon
            own = type(own)(**values)
        sides.append(own)
    values = {k: getattr(state, k) for k in inspect.signature(type(state)).parameters}
    values.update(side_one=sides[0], side_two=sides[1])
    return type(state)(**values)


def select_search_move(state, result):
    """Gate repeated Protect before applying any contextual move preferences."""
    streak = state.side_one.side_conditions.protect
    if streak > 0 and any(
        option.move_choice.removesuffix("-mega") == "protect" for option in result.side_one
    ) and random.random() < 1.0 - 3.0 ** -streak:
        options = [option for option in result.side_one
                   if option.move_choice.removesuffix("-mega") != "protect"]
        if not options:
            raise RuntimeError("Consecutive Protect was ignored but no alternative move is available")
        result = SimpleNamespace(side_one=options, side_two=result.side_two,
                                 total_visits=result.total_visits)
        if not any(option.visits > 0 for option in options):
            return random.choice(options).move_choice
    if healing_protect(state, result):
        return "protect"
    return select_move_from_mcts_results([(result, 1.0, 0)])


def healing_protect(state, result):
    """Break close search ties with a verified safe Leftovers recovery turn."""
    options = [option for option in result.side_one if option.visits > 0]
    protect = next((option for option in options if option.move_choice == "protect"), None)
    if protect is None:
        return False
    best_visits = max(option.visits for option in options)
    best_score = max(option.total_score / option.visits for option in options)
    if (protect.visits < best_visits * 0.75
            or protect.total_score / protect.visits < best_score - 0.01):
        return False
    user = state.side_one.pokemon[int(state.side_one.active_index)]
    opponent = state.side_two.pokemon[int(state.side_two.active_index)]
    if user.item.lower() != "leftovers" or user.hp >= user.maxhp:
        return False
    responses = [option.move_choice for option in result.side_two]
    if not responses:
        return False
    boosts = ("attack_boost", "defense_boost", "special_attack_boost",
              "special_defense_boost", "speed_boost", "accuracy_boost", "evasion_boost")
    for response in responses:
        branches = generate_instructions(state, "protect", response)
        if not branches:
            return False
        for branch in branches:
            if branch.percentage <= 0:
                continue
            outcome = state.apply_instructions(branch)
            healed = outcome.side_one.pokemon[int(outcome.side_one.active_index)]
            enemy = outcome.side_two.pokemon[int(outcome.side_two.active_index)]
            # This also rejects consecutive-Protect failure branches, residual
            # damage exceeding recovery, bypass attacks, setup and Substitute.
            if (healed.hp <= user.hp or healed.status.lower() != user.status.lower()
                    or enemy.hp > opponent.hp
                    or any(getattr(outcome.side_two, boost) > getattr(state.side_two, boost)
                           for boost in boosts)
                    or set(outcome.side_two.volatile_statuses) - set(state.side_two.volatile_statuses)):
                return False
    return True


@dataclass
class Turn:
    requests: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    snapshots: dict = field(default_factory=dict)
    error: Exception | None = None


class KnownSetMatch:
    """Synchronize requests before searching; neither side sees the other's choice."""
    def __init__(self, teams, search_time_ms):
        FoulPlayConfig.pokemon_format = "gen9customgame"
        self.teams = [export_to_dict(team) for team in teams]
        self.search_time_ms = search_time_ms
        self.turns = {}
        self.states = {}

    def finish(self, battle_tag):
        self.states.pop(battle_tag, None)
        for key in list(self.turns):
            if key[0] == battle_tag:
                self.turns.pop(key)

    def prepare(self, tag, turn):
        requests = turn.requests
        state = self.states.get(tag)
        first_turn = state is None
        if first_turn:
            state = Battle(tag)
            state.pokemon_format = "gen9customgame"
            state.generation = "gen9"
            state.mode = KnownSetsMode()
            for index, side in enumerate((state.user, state.opponent)):
                side.team_dict = self.teams[index]
                side.initialize_first_turn_user_from_json(requests[index])
                if side.active is None or side.reserve:
                    raise ValueError("Foul Play adapter requires one active Pokémon per side")
                side.active.original_ability = side.active.ability
            self.states[tag] = state

        state.request_json = requests[0]
        for message in turn.messages:
            action = message[1] if len(message) > 1 else ""
            if action in {"switch", "drag"}:
                if first_turn:
                    # Already initialized from exact private requests. Apply subsequent
                    # switch-in ability/weather messages normally, including Intimidate.
                    continue
                raise ValueError("Unexpected switch in a one-Pokémon battle")
            handler = MODIFIERS.get(action)
            if handler:
                getattr(protocol, handler)(state, message)

        # Requests contain exact HP (not the rounded opponent percentage), stats,
        # current items/abilities, legal moves, disabled flags, and remaining PP.
        for index, side in enumerate((state.user, state.opponent)):
            side.update_from_request_json(requests[index])
        for index in (0, 1):
            snapshot = deepcopy(state)
            if index == 1:
                snapshot.user, snapshot.opponent = snapshot.opponent, snapshot.user
            snapshot.request_json = requests[index]
            turn.snapshots[index] = snapshot

    async def choose(self, index, battle, request, messages):
        key = (battle.battle_tag, battle.turn)
        turn = self.turns.setdefault(key, Turn())
        turn.requests[index] = request
        if index == 0:
            turn.messages = messages
        if len(turn.requests) == 2 and not turn.ready.is_set():
            try:
                self.prepare(battle.battle_tag, turn)
            except Exception as error:
                turn.error = error
            finally:
                turn.ready.set()
        await turn.ready.wait()
        if turn.error:
            raise turn.error
        snapshot = turn.snapshots[index]
        decision = await asyncio.to_thread(self.search, snapshot)
        side = self.states[battle.battle_tag].user if index == 0 else self.states[battle.battle_tag].opponent
        side.last_selected_move = LastUsedMove(
            side.active.name, decision.removesuffix("-mega"), battle.turn
        )
        return decision

    def search(self, battle):
        state = battle_to_poke_engine_state(battle)
        # Engine objects are immutable; rebuild sides to preserve accuracy/evasion
        # stages that upstream's converter currently hard-codes to zero.
        sides = []
        for source, target in ((battle.user, state.side_one), (battle.opponent, state.side_two)):
            values = {name: getattr(target, name) for name in inspect.signature(type(target)).parameters}
            values.update(accuracy_boost=source.active.boosts["accuracy"],
                          evasion_boost=source.active.boosts["evasion"])
            # The engine infers Tera availability from the entire team. Mark a
            # fainted placeholder as spent so neither side can Tera, including
            # in future search turns, without changing the active's typing/STAB.
            pokemon = list(target.pokemon)
            placeholder = pokemon[-1]
            if placeholder.hp != 0:
                raise ValueError("Expected an empty reserve slot in a 1v1 search")
            placeholder_values = {
                name: getattr(placeholder, name)
                for name in inspect.signature(type(placeholder)).parameters
            }
            placeholder_values["terastallized"] = True
            pokemon[-1] = type(placeholder)(**placeholder_values)
            values["pokemon"] = pokemon
            sides.append(type(target)(**values))
        values = {name: getattr(state, name) for name in inspect.signature(type(state)).parameters}
        values.update(side_one=sides[0], side_two=sides[1])
        state = type(state)(**values)
        state = exclude_reflected_status_moves(state)
        result = monte_carlo_tree_search(state, self.search_time_ms, threads=1)
        if result.total_visits <= 0 or not result.side_one:
            raise RuntimeError("Foul Play search returned no policy; increase search_time_ms")
        return select_search_move(state, result)


class FoulPlayPlayer(Player):
    def __init__(self, *, match, side_index, **kwargs):
        self.match = match
        self.side_index = side_index
        self.pending_messages = {}
        self.requests = {}
        self.search_error = None
        super().__init__(**kwargs)

    async def _handle_battle_message(self, split_messages):
        tag = split_messages[0][0].lstrip(">")
        pending = self.pending_messages.setdefault(tag, [])
        for message in split_messages[1:]:
            action = message[1] if len(message) > 1 else ""
            # Showdown prefixes minor battle events with '-': item consumption,
            # ability activations, boosts, weather, misses, and other effects.
            if self.side_index == 0 and (action.startswith("-") or action in {
                "start", "turn", "upkeep", "move", "switch", "drag", "swap",
                "replace", "detailschange", "faint", "win", "tie", "cant", "error",
            }):
                logging.getLogger("simulation").info("%s %s", tag, "|".join(message))
            if len(message) > 2 and message[1] == "request" and message[2]:
                self.requests[tag] = json.loads(message[2])
            else:
                pending.append(message)
        await super()._handle_battle_message(split_messages)

    async def _handle_battle_request(self, battle, maybe_default_order=False):
        if maybe_default_order:
            self.search_error = RuntimeError("Showdown rejected the Foul Play choice")
            raise self.search_error
        await super()._handle_battle_request(battle)

    async def choose_move(self, battle):
        try:
            decision = await self.match.choose(
                self.side_index, battle, self.requests[battle.battle_tag],
                self.pending_messages.pop(battle.battle_tag, []),
            )
            if decision.endswith("-tera"):
                raise RuntimeError("Terastallization is disabled in simulations")
            mega = decision.endswith("-mega")
            move_id = decision.removesuffix("-mega")
            for move in battle.available_moves:
                if move.id == move_id:
                    if mega and not battle.can_mega_evolve:
                        raise RuntimeError("Foul Play selected unavailable Mega Evolution")
                    return self.create_order(move, mega=mega)
            raise RuntimeError(f"Foul Play selected unavailable move: {decision}")
        except Exception as error:
            # poke-env handles callbacks in background tasks. Preserve failures so
            # the runner can stop promptly rather than silently play a random move.
            self.search_error = error
            raise

    def _battle_finished_callback(self, battle):
        self.pending_messages.pop(battle.battle_tag, None)
        self.requests.pop(battle.battle_tag, None)
        self.match.finish(battle.battle_tag)
