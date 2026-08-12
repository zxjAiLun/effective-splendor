export const M22_RATING_REPORT = {
  format: "effective-splendor-rating-report", version: 1, tournament_id: "m22-scaled-self-play-v1",
  registry_hash: "8a13fa4ed4c1dfae9dbc0a1d625851628ab08c99dc12e70a161886de38a93063",
  round_robin_plan_hash: "df95640f34630633030b8f9a8294b290ff0f36d775e2a183834729aee3105b9b",
  scheduled_matches: 48, completed_matches: 48, aborted_matches: 0,
  agents: [
    { rank: 1, agent_id: "heuristic-v1", display_name: "Heuristic baseline", class: "baseline", completed: 24, aborted: 0, wins: 21, ties: 0, losses: 3, live_elo: 1666, official_elo: 1778, provisional: false },
    { rank: 2, agent_id: "m07-champion", display_name: "M07 determinization champion", class: "search", completed: 24, aborted: 0, wins: 15, ties: 0, losses: 9, live_elo: 1561, official_elo: 1580, provisional: false },
    { rank: 3, agent_id: "m18a-smoke", display_name: "M18A Self-Play · 2 games", class: "checkpoint", completed: 24, aborted: 0, wins: 6, ties: 0, losses: 18, live_elo: 1398, official_elo: 1321, provisional: false },
    { rank: 4, agent_id: "m22-scaled-self-play", display_name: "M22 Self-Play · 32 games · GPU", class: "checkpoint", completed: 24, aborted: 0, wins: 6, ties: 0, losses: 18, live_elo: 1375, official_elo: 1321, provisional: false },
  ],
  head_to_head: [
    ["heuristic-v1","m07-champion",6,2],["heuristic-v1","m18a-smoke",8,0],["heuristic-v1","m22-scaled-self-play",7,1],
    ["m07-champion","m18a-smoke",6,2],["m07-champion","m22-scaled-self-play",7,1],["m18a-smoke","m22-scaled-self-play",4,4],
  ].map(([agent_a, agent_b, wins_a, wins_b]) => ({ agent_a, agent_b, completed: 8, aborted: 0, wins_a, ties: 0, wins_b })),
  pair_evaluation_report_hashes: [
    "d26e666d0c23b467d1c3dca9b3433d19fe6e8129bf34cde6efce14c7b46c1588","f5de1fe535802b286727be0198c01e390b2b32fc7edd0bb5dae786c605dad25b","0b0ef3a3cc87fa61436e048a571c4388700586251930082180ba6237a9e8b4db","f54e14f6e111a321ed8591257890305f1bce5bce28351054f1f5eb26389b3f7f","25e302f6b927a173471bd8a405734fd04b74e9e8f3a9d48f16cd4abe07057257","89006e90b7c9c4cfd320ad0fab4670ca1c79d750c7d1e18d467aac63dd7ea24e"
  ],
} as const;
