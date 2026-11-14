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
                || move.id === 'whirlpool') {
                move.accuracy = 100;
            }
        },
    },
];
