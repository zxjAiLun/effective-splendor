// Engineering fixtures, NOT match evidence. The catalogue and opening view come
// from the tracked Rust-generated trace. Crowded/return/terminal states below are
// deliberately synthetic display cases; the mock does not implement game rules.
import fs from "node:fs";

const trace = JSON.parse(fs.readFileSync(new URL("./rust-analysis-trace-v2-m07-two-seat.json", import.meta.url), "utf8"));
export const catalog = trace.catalog;
const colours = ["white", "blue", "green", "red", "black", "gold"];
const tiers = ["One", "Two", "Three"];
const emptyGems = () => Object.fromEntries(colours.map(colour => [colour, 0]));

export function playFixture(scenario = "initial", seat = 0) {
  const opening = trace.frames[0];
  const state = {
    format: "effective-splendor-human-play-state", version: 1,
    session_id: "cockpit-ui-fixture", seed: "18446744073709551615", human_seat: seat,
    opponent: "★ Prism v0.1.1 (PPO Champion · 62.0% vs v0.3.1)", ply: 0,
    observation: structuredClone(opening.player_view),
    legal_actions: structuredClone(opening.legal_actions), action_history: [],
    result: null, replay_ready: false, replay_document_hash: null, league_completion: null,
  };
  state.observation.viewer = seat;
  state.observation.public.current_player = seat;
  if (scenario === "initial") return state;

  const pub = state.observation.public;
  const own = pub.players[seat];
  const opponent = pub.players[1 - seat];
  state.ply = 38;
  // Include all four printed cost colours and all five bonus colours.
  pub.market = [[5, 14, 22, 30], [40, 48, 56, 64], [70, 74, 79, 85]];
  own.tokens = { white: 2, blue: 1, green: 2, red: 1, black: 2, gold: 2 };
  own.bonuses = [2, 1, 3, 2, 1]; own.prestige = 11;
  own.purchased = [0, 1, 2, 3, 9, 10, 11, 12, 17]; own.nobles = [0];
  own.reserved_count = 3; own.public_reserved = [6, 21];
  state.observation.private.reserved = [6, 21, 87].map((card, slot) => ({ slot, card, tier: catalog.cards.find(c => c.id === card).tier, from_deck: slot === 2 }));
  opponent.tokens = { white: 1, blue: 1, green: 1, red: 1, black: 1, gold: 1 };
  opponent.bonuses = [1, 2, 2, 1, 2]; opponent.prestige = 12;
  opponent.purchased = [7, 15, 16, 18, 19, 20, 23, 24]; opponent.nobles = [1];
  opponent.reserved_count = 3; opponent.public_reserved = [13, 29];
  pub.bank = { white: 1, blue: 2, green: 1, red: 2, black: 1, gold: 2 };
  pub.nobles = [3, 4, 8]; pub.deck_counts = [17, 20, 12];
  const take = { ...emptyGems(), white: 1, blue: 1, green: 1 };
  const returns = [];
  // All 3-token returns that the fixture hand can cover after this take. Large
  // enough to catch an unbounded footer/rail without needing any real game.
  for (let a = 0; a < colours.length; a++) for (let b = a; b < colours.length; b++) for (let c = b; c < colours.length; c++) {
    const back = emptyGems();
    for (const index of [a, b, c]) back[colours[index]]++;
    if (colours.every(colour => back[colour] <= own.tokens[colour] + take[colour])) returns.push({ type: "take_tokens", take, return: back });
  }
  state.legal_actions = [
    ...(scenario === "returns" ? returns : [{ type: "take_tokens", take, return: { ...emptyGems(), white: 1, green: 1, black: 1 } }]),
    ...pub.market.flatMap((row, tier) => row.flatMap((_, slot) => [
      { type: "buy_market", tier: tiers[tier], slot },
      { type: "reserve_market", tier: tiers[tier], slot, return: { ...emptyGems(), gold: 1 } },
    ])),
    ...tiers.map(tier => ({ type: "reserve_deck", tier, return: { ...emptyGems(), gold: 1 } })),
    ...state.observation.private.reserved.map(({ slot }) => ({ type: "buy_reserved", slot })),
  ];
  const moves = [
    { type: "take_tokens", take, return: { ...emptyGems(), black: 1 } },
    { type: "reserve_deck", tier: "Three", return: { ...emptyGems(), gold: 1 } },
    { type: "buy_market", tier: "Two", slot: 0 },
    { type: "reserve_market", tier: "One", slot: 1, return: { ...emptyGems(), red: 1 } },
    { type: "choose_noble", noble: 0 },
  ];
  state.action_history = Array.from({ length: 24 }, (_, index) => ({
    ply: index + 1, actor: index % 2, action: moves[index % moves.length],
    card_id: [null, null, 41, 13, null][index % moves.length],
  }));
  if (scenario === "noble") {
    pub.phase = "choose_noble";
    state.legal_actions = [{ type: "choose_noble", noble: 3 }, { type: "choose_noble", noble: 4 }];
  }
  if (scenario === "pass") state.legal_actions = [{ type: "pass" }];
  if (scenario === "waiting") pub.current_player = 1 - seat;
  if (scenario === "overcap") own.tokens.gold += 2; // malformed-input visibility, never clamp to 10
  if (scenario === "finished") {
    state.result = { scores: seat === 0 ? [15, 12] : [12, 15], ranks: seat === 0 ? [1, 2] : [2, 1], winners: [seat], reason: "prestige" };
    state.legal_actions = []; state.replay_ready = true; state.replay_document_hash = "ab".repeat(32);
  }
  return state;
}

export function mockPlayHostScript() {
  const scenarios = Object.fromEntries(["initial", "crowded", "returns", "noble", "pass", "waiting", "overcap", "finished"].flatMap(name => [0, 1].map(seat => [`${name}-${seat}`, playFixture(name, seat)])));
  return `(() => {
    const catalogue = ${JSON.stringify(catalog)};
    const scenarios = ${JSON.stringify(scenarios)};
    const query = new URL(location.href).searchParams;
    let state = scenarios[(query.get('fixture') || 'crowded') + '-' + (query.get('seat') || '0')];
    window.fixtureCalls = []; window.fixtureActionMode = 'ok';
    const nativeFetch = window.fetch.bind(window);
    const reply = (body, status = 200) => new Response(JSON.stringify(body), {status, headers:{'Content-Type':'application/json'}});
    const advance = () => {
      state = {...state, ply: state.ply + 2};
      return reply(state);
    };
    window.fetch = async (url, options = {}) => {
      const address = new URL(String(url), location.href);
      if (address.origin !== 'http://127.0.0.1:43120') return nativeFetch(url, options);
      const route = address.pathname;
      window.fixtureCalls.push({route, method: options.method || 'GET', body: options.body || null});
      if (route === '/agents') return reply({agents:[{id:'prism-v011', display_name:state.opponent, class:'checkpoint'}]});
      if (route === '/catalog') return reply(catalogue);
      if (route === '/reviewers') return reply({reviewers:[]});
      if (route === '/state') return reply(state);
      if (route === '/action') {
        if (!state.legal_actions.some(action => JSON.stringify(action) === options.body)) return reply({error:'Not a fixture legal action'}, 400);
        if (window.fixtureActionMode === 'hold') return new Promise(resolve => {window.completeFixtureMove = () => resolve(advance());});
        if (window.fixtureActionMode === 'lost') { advance(); throw new Error('Fixture response lost'); }
        return advance();
      }
      return reply({error:'Unexpected mock Host route: ' + route}, 404);
    };
  })();`;
}
