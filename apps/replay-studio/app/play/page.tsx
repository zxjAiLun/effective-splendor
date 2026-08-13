"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { DevelopmentCard, EmptyDevelopmentCard, type DevelopmentCardData } from "../development-card";

type Action = { type: string; [key: string]: unknown };
type GemName = "white" | "blue" | "green" | "red" | "black" | "gold";
type Gems = Record<GemName, number>;
type Agent = { id:string; display_name:string; class:string; policy_version:string; model_version:string|null; checkpoint_hash:string|null };
type Reviewer = { id:string; display_name:string; description:string; competitive_status:"champion"|"experimental"|"rejected"; result_kind:"root_determinization"|"neural_ismcts"; is_default:boolean; available_metrics:string[]; estimated_cost:string };
type RecentGame = { session_id:string; opponent?:string|null; human_seat?:number|null; scores?:number[]; winners?:number[]; timestamp?:number|null; verification?:"verified"|"invalid"; available_reviews?:string[]; error?:string };
type Catalog = { cards:DevelopmentCardData[]; nobles:Array<{id:number;prestige:number;requirements:number[]}> };
type NobleData = Catalog["nobles"][number];
type Player = { id:number; tokens:Gems; bonuses:number[]; prestige:number; reserved_count:number; public_reserved:number[]; purchased:number[]; nobles:number[] };
type HistoryItem = { ply:number; actor:number; action:Action };
type State = {
  format:string; version:number; session_id:string; human_seat:number; opponent:string; ply:number;
  observation:{ viewer:number; public:{ current_player:number; phase:string; bank:Gems; deck_counts:number[]; market:Array<Array<number|null>>; nobles:number[]; players:Player[] }; private:{reserved:Array<{slot:number;card:number;tier:string;from_deck:boolean}>} };
  legal_actions:Action[]; action_history:HistoryItem[];
  result:null|{scores:number[];ranks:number[];winners:number[];reason:string}; replay_ready:boolean; replay_document_hash:string|null;
};

const API = "http://127.0.0.1:43120";
const TIERS = ["One", "Two", "Three"];
const GEM_NAMES: GemName[] = ["white", "blue", "green", "red", "black", "gold"];
const TAKE_GEMS: GemName[] = ["white", "blue", "green", "red", "black"];
const EMPTY_GEMS: Gems = { white:0, blue:0, green:0, red:0, black:0, gold:0 };
const GEM_LABELS: Record<GemName,string> = { white:"Diamond", blue:"Sapphire", green:"Emerald", red:"Ruby", black:"Onyx", gold:"Gold" };

function gemsOf(value:unknown):Gems {
  const source = value && typeof value === "object" ? value as Partial<Gems> : {};
  return Object.fromEntries(GEM_NAMES.map(gem => [gem, Number(source[gem] ?? 0)])) as Gems;
}

function sameGems(left:Gems,right:Gems) {
  return GEM_NAMES.every(gem => left[gem] === right[gem]);
}

function GemChip({gem,count,onClick,selected=false,disabled=false,source="token"}:{gem:GemName;count:number;onClick?:()=>void;selected?:boolean;disabled?:boolean;source?:"token"|"bonus"}) {
  const content = <><i aria-hidden="true"/><span>{GEM_LABELS[gem]}</span><b>{count}</b></>;
  const label=source==="bonus"?`${GEM_LABELS[gem]} permanent card bonuses ${count}`:`${GEM_LABELS[gem]} tokens ${count}`;
  const className=`table-gem table-gem-${gem} ${source==="bonus"?"card-bonus-gem":""} ${selected?"selected":""}`;
  return onClick ? <button type="button" className={className} disabled={disabled} onClick={onClick} aria-label={label}>{content}</button> : <span className={className} aria-label={label}>{content}</span>;
}

function PlayerResources({player}:{player:Player}) {
  const tokenTotal=GEM_NAMES.reduce((sum,gem)=>sum+player.tokens[gem],0);
  const bonusTotal=player.bonuses.reduce((sum,amount)=>sum+amount,0);
  return <div className="player-resource-table">
    <div className="player-resource-row"><span>TOKENS <b>{tokenTotal}/10</b></span><div>{GEM_NAMES.map(gem=><GemChip gem={gem} count={player.tokens[gem]} key={gem}/>)}</div></div>
    <div className="player-resource-row bonuses"><span>CARD BONUSES <b>{bonusTotal}</b></span><div>{TAKE_GEMS.map((gem,index)=><GemChip gem={gem} count={player.bonuses[index]??0} source="bonus" key={gem}/>)}</div></div>
  </div>;
}

function HistoryText({item,humanSeat}:{item:HistoryItem;humanSeat:number}) {
  const action=item.action;
  const actor=item.actor===humanSeat?"You":"Opponent";
  if(action.type==="take_tokens") return <><strong>{actor}</strong><span>took</span><GemStrip gems={gemsOf(action.take)}/>{GEM_NAMES.some(gem=>gemsOf(action.return)[gem]>0)?<><span>and returned</span><GemStrip gems={gemsOf(action.return)}/></>:null}</>;
  if(action.type==="buy_market") return <><strong>{actor}</strong><span>bought Tier {TIERS.indexOf(String(action.tier))+1}, slot {Number(action.slot)+1}</span></>;
  if(action.type==="buy_reserved") return <><strong>{actor}</strong><span>bought a reserved card</span></>;
  if(action.type==="reserve_market") return <><strong>{actor}</strong><span>reserved a face-up Tier {TIERS.indexOf(String(action.tier))+1} card</span></>;
  if(action.type==="reserve_deck") return <><strong>{actor}</strong><span>blind-reserved from Tier {TIERS.indexOf(String(action.tier))+1}</span></>;
  if(action.type==="choose_noble") return <><strong>{actor}</strong><span>welcomed noble #{String(action.noble)}</span></>;
  return <><strong>{actor}</strong><span>{action.type.replaceAll("_"," ")}</span></>;
}

function GemStrip({gems}:{gems:Gems}) {
  return <span className="history-gems">{GEM_NAMES.flatMap(gem=>Array.from({length:gems[gem]},(_,index)=><i className={`history-gem gem-${gem}`} title={GEM_LABELS[gem]} key={`${gem}-${index}`}/>))}</span>;
}

function NobleTile({noble,owned=false,selectable=false,disabled=false,onClick}:{noble:NobleData;owned?:boolean;selectable?:boolean;disabled?:boolean;onClick?:()=>void}) {
  const body=<><div className="table-noble-top"><strong>{noble.prestige}</strong><span>{owned?"ACQUIRED":"NOBLE"}</span></div><div className="table-noble-name">NOBLE #{noble.id}</div><div className="table-noble-cost">{noble.requirements.map((amount,index)=>amount>0?<span className={`gem gem-${TAKE_GEMS[index]}`} key={index}>{amount}</span>:null)}</div></>;
  return selectable?<button type="button" className="table-noble selectable" disabled={disabled} onClick={onClick} aria-label={`Choose noble ${noble.id}, ${noble.prestige} prestige`}>{body}</button>:<div className={`table-noble ${owned?"owned":""}`} aria-label={`Noble ${noble.id}, ${noble.prestige} prestige`}>{body}</div>;
}

function actionReturns(action:Action) { return gemsOf(action.return); }

export default function HumanPlayPage() {
  const [state,setState] = useState<State|null>(null);
  const [agents,setAgents] = useState<Agent[]>([]);
  const [reviewers,setReviewers] = useState<Reviewer[]>([]);
  const [recentGames,setRecentGames] = useState<RecentGame[]>([]);
  const [showReviewers,setShowReviewers] = useState(false);
  const [catalog,setCatalog] = useState<Catalog|null>(null);
  const [agentId,setAgentId] = useState("m07-champion");
  const [humanSeat,setHumanSeat] = useState(0);
  const [seed,setSeed] = useState(()=>Math.floor(Date.now()/1000));
  const [hostOnline,setHostOnline] = useState(false);
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  const [pendingTake,setPendingTake] = useState<Gems>(EMPTY_GEMS);
  const [selectedCard,setSelectedCard] = useState<{tier:number;slot:number;cardId:number}|null>(null);
  const [contextActions,setContextActions] = useState<Action[]>([]);
  const cards = useMemo(() => new Map((catalog?.cards ?? []).map(card => [card.id, card])), [catalog]);
  const nobles = useMemo(() => new Map((catalog?.nobles ?? []).map(noble => [noble.id, noble])), [catalog]);
  const takeActions = useMemo(() => (state?.legal_actions ?? []).filter(action=>action.type==="take_tokens"), [state?.legal_actions]);
  const exactTakeActions = useMemo(() => takeActions.filter(action=>sameGems(gemsOf(action.take),pendingTake)), [pendingTake,takeActions]);

  useEffect(()=>{ queueMicrotask(()=>void (async()=>{
    try {
      const [agentResponse,catalogResponse]=await Promise.all([fetch(`${API}/agents`),fetch(`${API}/catalog`)]);
      if(!agentResponse.ok)throw new Error(`Studio Host ${agentResponse.status}`); if(!catalogResponse.ok)throw new Error(`Catalog ${catalogResponse.status}`);
      const [value,catalogValue]=await Promise.all([agentResponse.json() as Promise<{agents:Agent[]}>,catalogResponse.json() as Promise<Catalog>]);
      setAgents(value.agents); setCatalog(catalogValue); setHostOnline(true); setError("");
      setAgentId(current=>value.agents.some(agent=>agent.id===current)?current:(value.agents[0]?.id??""));
      const stateResponse=await fetch(`${API}/state`); if(stateResponse.ok)setState(await stateResponse.json());
      try { const reviewerResponse=await fetch(`${API}/reviewers`); if(reviewerResponse.ok){ const reviewerValue=await reviewerResponse.json() as {reviewers:Reviewer[]}; setReviewers(reviewerValue.reviewers); } } catch { /* reviewers optional */ }
      try { const recentResponse=await fetch(`${API}/recent-games`); if(recentResponse.ok){ const recentValue=await recentResponse.json() as {games:RecentGame[]}; setRecentGames(recentValue.games); } } catch { /* recent games optional */ }
    } catch(reason){ setHostOnline(false); setError(`Studio Host is not running. Launch the project once with Start Splendor Studio.cmd. ${reason instanceof Error?reason.message:String(reason)}`); }
  })()); },[]);

  function clearPending(){ setPendingTake(EMPTY_GEMS); setSelectedCard(null); setContextActions([]); }
  async function startGame(){ setBusy(true); try { const response=await fetch(`${API}/games`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({agent_id:agentId,human_seat:humanSeat,seed})}); const value=await response.json(); if(!response.ok)throw new Error(value.error??`Studio Host ${response.status}`); setState(value); clearPending(); setError(""); } catch(reason){ setError(reason instanceof Error?reason.message:String(reason)); } finally{setBusy(false);} }
  async function play(action:Action){ setBusy(true); try { const response=await fetch(`${API}/action`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(action)}); const value=await response.json(); if(!response.ok) throw new Error(value.error??`Studio Host ${response.status}`); setState(value); clearPending(); setError(""); } catch(reason){ setError(reason instanceof Error?reason.message:String(reason)); } finally { setBusy(false); } }
  async function openReplay(){ setBusy(true); try { const response=await fetch(`${API}/archive`); const value=await response.json(); if(!response.ok) throw new Error(value.error??`Studio Host ${response.status}`); sessionStorage.setItem("effective-splendor-human-replay",JSON.stringify(value)); window.location.assign("/?humanReplay=1"); } catch(reason){ setError(reason instanceof Error?reason.message:String(reason)); setBusy(false); } }

  function changePendingGem(gem:GemName,delta:number){
    const candidate={...pendingTake,[gem]:Math.max(0,pendingTake[gem]+delta)};
    const isPrefix=takeActions.some(action=>TAKE_GEMS.every(color=>candidate[color]<=gemsOf(action.take)[color]));
    if(delta<0||isPrefix){ setPendingTake(candidate); setSelectedCard(null); setContextActions([]); }
  }
  function openCard(tier:number,slot:number,cardId:number){
    const actions=(state?.legal_actions??[]).filter(action=>(action.type==="buy_market"||action.type==="reserve_market")&&action.tier===TIERS[tier]&&action.slot===slot);
    setSelectedCard({tier,slot,cardId}); setContextActions(actions); setPendingTake(EMPTY_GEMS);
  }
  function openDeck(tier:number){
    setSelectedCard(null); setContextActions((state?.legal_actions??[]).filter(action=>action.type==="reserve_deck"&&action.tier===TIERS[tier])); setPendingTake(EMPTY_GEMS);
  }
  function openReserved(slot:number,cardId:number){
    setSelectedCard({tier:-1,slot,cardId}); setContextActions((state?.legal_actions??[]).filter(action=>action.type==="buy_reserved"&&action.slot===slot)); setPendingTake(EMPTY_GEMS);
  }

  const confirmTake = exactTakeActions.length===1 ? exactTakeActions[0] : null;
  const pendingCount=TAKE_GEMS.reduce((sum,gem)=>sum+pendingTake[gem],0);
  const defaultReviewerId=reviewers.find(reviewer=>reviewer.is_default)?.id??reviewers[0]?.id??"";
  return <main className="human-studio">
    <header className="human-topbar"><div><span className="section-kicker">LOCAL 1V1 · TABLE CONTROLS</span><h1>Human Play Studio</h1></div><div className="human-status"><span className={`status-dot ${hostOnline?"":"offline"}`} />{state?`${state.opponent} · ply ${state.ply}`:hostOnline?"Studio Host ready":"Studio Host offline"}</div><nav><Link href="/">Replay Studio</Link><Link href="/ratings">Ratings</Link>{state?<button onClick={()=>{setState(null);clearPending();}}>New game</button>:null}</nav></header>
    {error?<div className="error-banner" role="alert">{error}</div>:null}
    {state?<section className="human-workspace">
      <article className="human-board">
        <div className="human-score">{state.observation.public.players.map(item=><div className={item.id===state.human_seat?"you":""} key={item.id}><span>{item.id===state.human_seat?"YOU":"OPPONENT"}</span><strong>{item.prestige}<small> VP</small></strong><small>{item.reserved_count} reserved · {item.purchased.length} developments · {item.nobles.length} nobles</small><PlayerResources player={item}/>{item.nobles.length?<div className="owned-nobles">{item.nobles.map(id=>nobles.has(id)?<NobleTile noble={nobles.get(id)!} owned key={id}/>:null)}</div>:null}</div>)}</div>
        <div className="human-bank"><span><b>BANK</b><small>Click gems to build a legal take</small></span>{GEM_NAMES.map(gem=><GemChip gem={gem} count={state.observation.public.bank[gem]} selected={pendingTake[gem]>0} disabled={busy||gem==="gold"||state.result!==null} onClick={()=>changePendingGem(gem,1)} key={gem}/>)}</div>
        <section className="table-nobles"><div><b>NOBLES</b><small>{state.observation.public.nobles.length} available · requirements use permanent bonuses</small></div>{state.observation.public.nobles.map(id=>{const noble=nobles.get(id);const action=state.legal_actions.find(candidate=>candidate.type==="choose_noble"&&candidate.noble===id);return noble?<NobleTile noble={noble} selectable={Boolean(action)} disabled={!action||busy} onClick={()=>{if(action)void play(action);}} key={id}/>:null;})}</section>
        {state.observation.private.reserved.length?<section className="reserved-tray"><span>YOUR RESERVE</span>{state.observation.private.reserved.map(reserved=>cards.has(reserved.card)?<DevelopmentCard card={cards.get(reserved.card)!} interactive affordable={(state.legal_actions).some(action=>action.type==="buy_reserved"&&action.slot===reserved.slot)} disabled={busy} onClick={()=>openReserved(reserved.slot,reserved.card)} slotLabel={`reserve ${reserved.slot+1}`} key={reserved.slot}/>:null)}</section>:null}
        <div className="human-market">{[2,1,0].map(tier=><div className="human-tier" key={tier}><button type="button" className="tier-deck" disabled={busy||state.observation.public.deck_counts[tier]===0} onClick={()=>openDeck(tier)}><span>TIER {tier+1}</span><b>{state.observation.public.deck_counts[tier]}</b><small>click to blind reserve</small></button>{state.observation.public.market[tier].map((cardId,slot)=>{const card=cardId==null?null:cards.get(cardId);return card?<DevelopmentCard card={card} interactive affordable={state.legal_actions.some(action=>action.type==="buy_market"&&action.tier===TIERS[tier]&&action.slot===slot)} disabled={busy} onClick={()=>openCard(tier,slot,cardId!)} slotLabel={`slot ${slot+1}`} key={slot}/>:<EmptyDevelopmentCard key={slot}/>;})}</div>)}</div>
        <div className="human-private"><span>PLAYER-VIEW ONLY</span><p>Actions and token holdings are public. Blind-reserved card identities and deck order remain hidden.</p></div>
      </article>
      <aside className="human-actions">
        {state.result?<div className="human-result"><strong>{state.result.winners.includes(state.human_seat)?"VICTORY":"DEFEAT"}</strong><span>{state.result.scores.join(" – ")} · {state.result.reason.replaceAll("_"," ")}</span>{state.replay_ready?<><button disabled={busy} onClick={()=>void openReplay()}>Open replay</button><button disabled={busy} onClick={()=>setShowReviewers(prev=>!prev)}>Review this game</button>{showReviewers?<div className="review-pick"><span className="section-kicker">CHOOSE A REVIEWER</span>{reviewers.map(reviewer=><button key={reviewer.id} onClick={()=>window.location.assign(`/review?session=${encodeURIComponent(state.session_id)}&reviewer=${encodeURIComponent(reviewer.id)}&seat=${state.human_seat}`)}><strong>{reviewer.display_name}</strong><small>{reviewer.competitive_status==="rejected"?"Experimental · Formal promotion rejected":reviewer.competitive_status} · {reviewer.estimated_cost==="cpu"?"CPU":reviewer.estimated_cost}{reviewer.is_default?" · recommended default":""}</small></button>)}{reviewers.length===0?<small>No reviewers registered.</small>:null}</div>:null}</>:null}{state.replay_document_hash?<code>{state.replay_document_hash.slice(0,12)}…</code>:null}</div>:<>
          <section className="pending-panel"><span className="section-kicker">PENDING MOVE</span><h2>{pendingCount?"Take gems":selectedCard?`Card #${selectedCard.cardId}`:contextActions.some(action=>action.type==="reserve_deck")?"Blind reserve":"Select on the table"}</h2>
            {pendingCount?<><div className="pending-gems">{TAKE_GEMS.filter(gem=>pendingTake[gem]>0).map(gem=><GemChip gem={gem} count={pendingTake[gem]} selected onClick={()=>changePendingGem(gem,-1)} key={gem}/>)}</div><p>{confirmTake?"Legal selection. Confirm to end your turn.":exactTakeActions.length>1?"Choose which gems to return below.":"Keep selecting a legal combination, or click a selected gem to return it."}</p></>:null}
            {selectedCard&&cards.has(selectedCard.cardId)?<div className="selected-card-preview"><DevelopmentCard card={cards.get(selectedCard.cardId)!}/></div>:null}
            {contextActions.length?<div className="context-actions">{contextActions.map((action,index)=><button disabled={busy} onClick={()=>void play(action)} key={index}><strong>{action.type==="buy_market"||action.type==="buy_reserved"?"Buy card":action.type==="reserve_market"?"Reserve card":"Blind reserve"}</strong>{GEM_NAMES.some(gem=>actionReturns(action)[gem]>0)?<span>Return <GemStrip gems={actionReturns(action)}/></span>:<small>{action.type.startsWith("reserve")?"Gain gold if available":"Pay with tokens and bonuses"}</small>}</button>)}</div>:null}
            {exactTakeActions.length>1?<div className="context-actions">{exactTakeActions.map((action,index)=><button disabled={busy} onClick={()=>void play(action)} key={index}><strong>Confirm take</strong><span>Return <GemStrip gems={actionReturns(action)}/></span></button>)}</div>:null}
            {confirmTake?<button className="confirm-move" disabled={busy} onClick={()=>void play(confirmTake)}>Confirm take</button>:null}
            {!pendingCount&&!selectedCard&&!contextActions.length&&state.legal_actions.some(action=>action.type==="choose_noble")?<div className="context-actions">{state.legal_actions.filter(action=>action.type==="choose_noble").map((action,index)=><button onClick={()=>void play(action)} key={index}><strong>Choose noble #{String(action.noble)}</strong></button>)}</div>:null}
            {!pendingCount&&!selectedCard&&!contextActions.length&&state.legal_actions.some(action=>action.type==="pass")?<button className="confirm-move" onClick={()=>void play(state.legal_actions.find(action=>action.type==="pass")!)}>Pass turn</button>:null}
            {(pendingCount||selectedCard||contextActions.length)?<button className="cancel-move" onClick={clearPending}>Cancel selection</button>:null}
          </section>
          <section className="history-panel"><span className="section-kicker">PUBLIC HISTORY</span><h2>Recent moves</h2>{state.action_history.length?<ol>{state.action_history.toReversed().slice(0,10).map(item=><li className={item.actor===state.human_seat?"mine":"opponent"} key={item.ply}><small>PLY {item.ply}</small><div><HistoryText item={item} humanSeat={state.human_seat}/></div></li>)}</ol>:<p>No moves yet. Your confirmed move will appear here.</p>}</section>
        </>}
      </aside>
    </section>:null}
    {!state?<><section className="human-connect"><span>ONE CLICK · NO PORT SETUP</span><h2>Start a local game</h2><p>Choose any registered baseline, search agent or GPU checkpoint and start immediately.</p><label>Opponent<select value={agentId} onChange={event=>setAgentId(event.target.value)} disabled={!hostOnline||busy}>{agents.map(agent=><option value={agent.id} key={agent.id}>{agent.display_name}{agent.class==="checkpoint"?" · checkpoint":""}</option>)}</select></label><label>Your seat<select value={humanSeat} onChange={event=>setHumanSeat(Number(event.target.value))} disabled={!hostOnline||busy}><option value={0}>P0 · first</option><option value={1}>P1 · second</option></select></label><label>Game seed<input type="number" min="0" value={seed} onChange={event=>setSeed(Number(event.target.value))} disabled={!hostOnline||busy}/></label><button onClick={()=>void startGame()} disabled={!hostOnline||!agentId||busy}>{busy?"Starting agent…":"Start new game"}</button><small>{hostOnline?`${agents.length} registered agents ready`:`Double-click Start Splendor Studio.cmd in the project folder.`}</small></section><section className="recent-games"><span className="section-kicker">RECENT VERIFIED GAMES</span><h2>Review an earlier game</h2>{recentGames.length?<div className="recent-game-list">{recentGames.slice(0,8).map(game=><article key={game.session_id}><div><strong>{game.session_id}</strong><small>{game.error??`${game.scores?.join(" – ")??"—"} · ${game.opponent??"unknown opponent"}`}</small></div><div><span>{game.verification??"unreadable"}</span><small>{game.available_reviews?.length??0} cached reviews</small>{game.verification==="verified"&&defaultReviewerId?<Link href={`/review?session=${encodeURIComponent(game.session_id)}&reviewer=${encodeURIComponent(defaultReviewerId)}&seat=${game.human_seat??0}`}>Review →</Link>:null}</div></article>)}</div>:<p>No verified local games yet.</p>}</section></>:null}
  </main>;
}
