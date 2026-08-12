export const M19_RATING_REPORT = {
  format: "effective-splendor-rating-report", version: 1, tournament_id: "m19-internal-championship-v1",
  registry_hash: "a7a999e79b33114e209bb810779eb9301a94a783965c49d985afed0db90b8a5c",
  round_robin_plan_hash: "4e6799c6c9af1f699d26dd17ef9b30e171388e3713fc4ef31d5411c005ba5949",
  scheduled_matches: 42, completed_matches: 42, aborted_matches: 0,
  agents: [
    { rank: 1, agent_id: "heuristic-v1", display_name: "Heuristic baseline", class: "baseline", completed: 12, aborted: 0, wins: 11, ties: 0, losses: 1, live_elo: 1619, official_elo: 1908, provisional: true },
    { rank: 2, agent_id: "m07-champion", display_name: "M07 determinization champion", class: "search", completed: 12, aborted: 0, wins: 8, ties: 0, losses: 4, live_elo: 1549, official_elo: 1637, provisional: true },
    { rank: 3, agent_id: "m10-ismcts", display_name: "M10 ISMCTS", class: "search", completed: 12, aborted: 0, wins: 7, ties: 0, losses: 5, live_elo: 1534, official_elo: 1567, provisional: true },
    { rank: 4, agent_id: "m17-entity-mixer", display_name: "M17 Entity Mixer · GPU", class: "checkpoint", completed: 12, aborted: 0, wins: 7, ties: 0, losses: 5, live_elo: 1528, official_elo: 1567, provisional: true },
    { rank: 5, agent_id: "m18a-self-play", display_name: "M18A Self-Play Neural ISMCTS · GPU", class: "checkpoint", completed: 12, aborted: 0, wins: 5, ties: 0, losses: 7, live_elo: 1464, official_elo: 1429, provisional: true },
    { rank: 6, agent_id: "m13-neural-ismcts", display_name: "M13 Neural ISMCTS", class: "checkpoint", completed: 12, aborted: 0, wins: 2, ties: 0, losses: 10, live_elo: 1398, official_elo: 1196, provisional: true },
    { rank: 7, agent_id: "m18b-rainbow", display_name: "M18B Rainbow · GPU", class: "checkpoint", completed: 12, aborted: 0, wins: 2, ties: 0, losses: 10, live_elo: 1408, official_elo: 1196, provisional: true },
  ],
  head_to_head: [
    ["heuristic-v1","m07-champion",2,0],["heuristic-v1","m10-ismcts",2,0],["heuristic-v1","m13-neural-ismcts",2,0],["heuristic-v1","m17-entity-mixer",2,0],["heuristic-v1","m18a-self-play",1,1],["heuristic-v1","m18b-rainbow",2,0],
    ["m07-champion","m10-ismcts",2,0],["m07-champion","m13-neural-ismcts",2,0],["m07-champion","m17-entity-mixer",1,1],["m07-champion","m18a-self-play",1,1],["m07-champion","m18b-rainbow",2,0],
    ["m10-ismcts","m13-neural-ismcts",2,0],["m10-ismcts","m17-entity-mixer",1,1],["m10-ismcts","m18a-self-play",2,0],["m10-ismcts","m18b-rainbow",2,0],
    ["m13-neural-ismcts","m17-entity-mixer",1,1],["m13-neural-ismcts","m18a-self-play",0,2],["m13-neural-ismcts","m18b-rainbow",1,1],
    ["m17-entity-mixer","m18a-self-play",2,0],["m17-entity-mixer","m18b-rainbow",2,0],["m18a-self-play","m18b-rainbow",1,1],
  ].map(([agent_a, agent_b, wins_a, wins_b]) => ({ agent_a, agent_b, completed: 2, aborted: 0, wins_a, ties: 0, wins_b })),
  pair_evaluation_report_hashes: [
    "b8bf15262d1a0be008293d473507dad6d85d1f65667f2056e93aa61cbaab1e48","c1a175aff05c7091ea144df3869b179005ce51f31886912752380ab4b36efb77","7e7ee3ec674fa060c2f31c1aac8ca3d35f3a3b4a3760cdfe3f40b4d25724db3a","5554d2771d917736ba5de070164888bbf2b19a224f4ed44fa7e632a6222f78af","fab6d35e4e6fef37115ca33096e256675596845d9be563420382544b4f9b7b34","16e9fbb33bb1023183268d3de5eebb394be5173b7edaca5909fbdb0532ab650f","4224010a1a6126ccafcfea0e5812608301ed2da23622880dd5b239d7e94a5a2c","942bd5742027e7396fe967273ffbbc2330178a33314c9bb24b11a6d0c468f91c","e60ea5304101c6289fe65ad2aa878b80951b90ea624e97ffd591a12dbafa3730","1d23dd79f11dddbe7dbf4e5874207f4b8d6121b44c81d00f4a06a597a1ddea6c","598f80d47c93d1201bec0ef62dde09b071bc88f134e92d08625ba31083742f79","4107e9672b2114a4ec5d6714b1289ffc1b74d64416307d2c87fa7fe263e76816","13719f83e9b143abf84fdb11a399c412d4389cca92007dd52b6a4a9984d45000","0c09c0645df230c5a2b6a7caddcd60dee3f7fa93e8c2fb6264741c25d8155984","274c7a53fc4fe569851d5d1e6c2d93a720b81a4c688e53a6063226aefd2fb0a8","0182d8acc08254e6687891f328b5af7557987723161ae67c5e79af7fd5c052ed","8767d58039d830cb196c46917bfbd0465ef4ffe6c13ffa68d634a8d39aae21cb","e91fd0447ad98be0ef75a2838f4e9a0b4e60dd3790cb78e9f25adf04fa3483ed","66f0f6c7e46a0d59b8370d81cd8d5acec06786a7f0fe1a161a52fe1239b17ebb","a2dc782ef33b95ae35ade3f5593b0fc555203c620aab1334574de0f0bb94280a","29dbe3e6723a731ef3ef38c12f7070f7c1b278896c744014a73742e74dd332e6"
  ],
} as const;
