// Installed by attempt.py before starting the local Showdown server.
export const Formats: import('../sim/dex-formats').FormatList = [
    {
        section: "Local simulations",
    },
    {
        name: "[Gen 9] Local Simulation",
        mod: 'gen9',
        searchShow: false,
        debug: true,
        battle: { trunc: Math.trunc },
        ruleset: ['[Gen 9] Custom Game', 'Terastal Clause'],
        onResidualOrder: 1000,
        onResidual() {
            if (this.turn >= 100 && !this.ended) {
                this.resolveFaints({checkWinIfNoFaints: true});
                if (!this.ended) {
                    this.add('message', '100-turn limit reached: draw.');
                    this.tie();
                }
            }
        },
    },
    {
        name: "[Gen 9] Accuracy Changes",
        mod: 'gen9',
        searchShow: false,
        debug: true,
        battle: { trunc: Math.trunc },
        ruleset: ['[Gen 9] Local Simulation'],
        onModifyMove(move) {
            if (move.id === 'skyattack' || move.id === 'highhorsepower' 
                || move.id === 'sandtomb' || move.id === 'playrough'
                || move.id === 'ruination' || move.id === 'drillrun'
                || move.id === 'whirlpool' || move.id === 'screech'
                || move.id === 'meteorbeam'
                ) {
                move.accuracy = 100;
            }
        },
    },
];
