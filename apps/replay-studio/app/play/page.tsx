"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE as API, BASE_PATH } from "../api-base.mjs";
import { visibleAgents, visibleParticipant, visibleReviewers } from "../agent-visibility.mjs";
import { DevelopmentCard, EmptyDevelopmentCard, HiddenDevelopmentCard, type DevelopmentCardData } from "../development-card";
import { defaultReviewerIdFor, reviewerSupportsPlayerCount } from "../trace-runtime.mjs";
import { PlayerHandCard, PlayerStateStrip, type StripPlayerView } from "../components/player-state-strip";
import { StructuredAction, type ActionCatalog } from "../components/structured-action";
import { humanResult, humanStartBody, randomSeed, resolveSeat, retryHumanBooking } from "../human-play-runtime.mjs";
import { HumanBookingPanel, type HumanCompletion } from "../components/human-booking-panel";
import { StudioBrand, StudioGlyph, StudioHeader, StudioIntro, StudioTableArt } from "../components/studio-chrome";
import "./play.css";

type Action = { type: string; [key: string]: unknown };
type GamePanel = "table" | "move" | "reserves" | "history";
type GemName = "white" | "blue" | "green" | "red" | "black" | "gold";
type Gems = Record<GemName, number>;
type Agent = { id:string; display_name:string; class:string; policy_version:string; model_version:string|null; checkpoint_hash:string|null };
type Reviewer = { id:string; display_name:string; description:string; competitive_status:"champion"|"experimental"|"rejected"; result_kind:"root_determinization"|"neural_ismcts"|"policy_recommendation"; supported_player_counts:number[]; default_for_player_counts:number[]; available_metrics:string[]; estimated_cost:string };
type Catalog = { cards:DevelopmentCardData[]; nobles:Array<{id:number;prestige:number;requirements:number[]}> };
type NobleData = Catalog["nobles"][number];
type Player = { id:number; tokens:Gems; bonuses:number[]; prestige:number; reserved_count:number; public_reserved:number[]; purchased:number[]; nobles:number[] };
type HistoryItem = { ply:number; actor:number; action:Action; card_id?: number | null };
type State = {
  format:string; version:number; session_id:string; human_seat:number; opponent:string; ply:number;
  observation:{ viewer:number; public:{ player_count:number; current_player:number; phase:string; bank:Gems; deck_counts:number[]; market:Array<Array<number|null>>; nobles:number[]; players:Player[] }; private:{reserved:Array<{slot:number;card:number;tier:string;from_deck:boolean}>} };
  legal_actions:Action[]; action_history:HistoryItem[];
  result:null|{scores:number[];ranks:number[];winners:number[];reason:string}; replay_ready:boolean; replay_document_hash:string|null;
  seed?:string; league_completion?:HumanCompletion|null;
};

const TIERS = ["One", "Two", "Three"];
const GEM_NAMES: GemName[] = ["white", "blue", "green", "red", "black", "gold"];
const TAKE_GEMS: GemName[] = ["white", "blue", "green", "red", "black"];
const EMPTY_GEMS: Gems = { white:0, blue:0, green:0, red:0, black:0, gold:0 };
const GEM_LABELS: Record<GemName,string> = { white:"Diamond", blue:"Sapphire", green:"Emerald", red:"Ruby", black:"Onyx", gold:"Gold" };
const GEM_CODES: Record<GemName,string> = { white:"W", blue:"U", green:"G", red:"R", black:"K", gold:"★" };

function gemsOf(value:unknown):Gems {
  const source = value && typeof value === "object" ? value as Partial<Gems> : {};
  return Object.fromEntries(GEM_NAMES.map(gem => [gem, Number(source[gem] ?? 0)])) as Gems;
}

function sameGems(left:Gems,right:Gems) {
  return GEM_NAMES.every(gem => left[gem] === right[gem]);
}

function GemChip({gem,count,onClick,selected=false,selectedCount=0,disabled=false,source="token"}:{gem:GemName;count:number;onClick?:()=>void;selected?:boolean;selectedCount?:number;disabled?:boolean;source?:"token"|"bonus"}) {
  const content = <><i aria-hidden="true">{GEM_CODES[gem]}</i><span>{GEM_LABELS[gem]}</span><b>{count}</b>{selectedCount>0?<em className="bank-selected-count" aria-hidden="true">+{selectedCount}</em>:null}</>;
  const label=source==="bonus"?`${GEM_LABELS[gem]} permanent card bonuses ${count}`:`${GEM_LABELS[gem]} tokens ${count}${selectedCount>0?`, ${selectedCount} selected`:""}`;
  const className=`table-gem table-gem-${gem} ${source==="bonus"?"card-bonus-gem":""} ${selected?"selected":""}`;
  return onClick ? <button type="button" className={className} disabled={disabled} onClick={onClick} aria-label={label} aria-pressed={selected} title={label}>{content}</button> : <span className={className} aria-label={label} title={label}>{content}</span>;
}

/**
 * Cards an opponent reserved face-up from the market. These identities are
 * public in Splendor, but the table previously showed only a count, hiding
 * information the player is entitled to. Blind reserves taken from a deck stay
 * face-down.
 */
function OpponentReserve({player,cards}:{player:Player;cards:Map<number,DevelopmentCardData>}) {
  const hidden=Math.max(0,player.reserved_count-player.public_reserved.length);
  if(!player.reserved_count) return null;
  return <div className="opponent-reserve">
    <div className="reserved-heading"><small>THEIR RESERVE {player.reserved_count}</small>{hidden>0?<em>{hidden} blind-reserved · identity hidden</em>:null}</div>
    <div className="reserved-cards">
      {player.public_reserved.map(id=>cards.has(id)?<DevelopmentCard card={cards.get(id)!} variant="mini" slotLabel="public" key={id}/>:null)}
      {hidden>0?<HiddenDevelopmentCard count={hidden} variant="mini"/>:null}
    </div>
  </div>;
}

/**
 * One history entry, through the shared action renderer.
 *
 * Card identity is resolved from item.card_id provided by the backend snapshot.
 */
function HistoryText({item,humanSeat,cards,nobles}:{item:HistoryItem;humanSeat:number;cards:ActionCatalog["cards"];nobles:ActionCatalog["nobles"]}) {
  const actor=item.actor===humanSeat?"You":"Opponent";
  const actionWithCard = item.card_id != null ? { ...item.action, card_id: item.card_id } : item.action;
  return <div className="history-entry"><strong>{actor}</strong><StructuredAction action={actionWithCard} cardId={item.card_id} cards={cards} nobles={nobles} variant="compact"/></div>;
}

function GemStrip({gems}:{gems:Gems}) {
  return <span className="history-gems" aria-label={GEM_NAMES.filter(gem=>gems[gem]>0).map(gem=>`${gems[gem]} ${GEM_LABELS[gem]}`).join(", ")}>{GEM_NAMES.filter(gem=>gems[gem]>0).map(gem=><span className={`return-gem table-gem-${gem}`} key={gem}><i aria-hidden="true">{GEM_CODES[gem]}</i><b>{gems[gem]}</b></span>)}</span>;
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
  const [showReviewers,setShowReviewers] = useState(false);
  const [catalog,setCatalog] = useState<Catalog|null>(null);
  const [agentId,setAgentId] = useState("s3-rollout");
  const [seatChoice,setSeatChoice] = useState("random");
  const [seed,setSeed] = useState("0");
  const [hostOnline,setHostOnline] = useState(false);
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  const [uncertain,setUncertain] = useState(false);
  const [pendingTake,setPendingTake] = useState<Gems>(EMPTY_GEMS);
  const [selectedCard,setSelectedCard] = useState<{tier:number;slot:number;cardId:number}|null>(null);
  const [selectedDeck,setSelectedDeck] = useState<number|null>(null);
  const [panel,setPanel] = useState<GamePanel>("table");
  const panelRef = useRef<HTMLElement>(null);
  const [contextActions,setContextActions] = useState<Action[]>([]);
  const cards = useMemo(() => new Map((catalog?.cards ?? []).map(card => [card.id, card])), [catalog]);
  const nobles = useMemo(() => new Map((catalog?.nobles ?? []).map(noble => [noble.id, noble])), [catalog]);
  const takeActions = useMemo(() => (state?.legal_actions ?? []).filter(action=>action.type==="take_tokens"), [state?.legal_actions]);
  const exactTakeActions = useMemo(() => takeActions.filter(action=>sameGems(gemsOf(action.take),pendingTake)), [pendingTake,takeActions]);

  useEffect(()=>{
    if(panel!=="table") panelRef.current?.focus({preventScroll:true});
  },[panel]);

  useEffect(()=>{ queueMicrotask(()=>void (async()=>{
    try {
      setSeed(randomSeed());
      const [agentResponse,catalogResponse]=await Promise.all([fetch(`${API}/agents`),fetch(`${API}/catalog`)]);
      if(!agentResponse.ok)throw new Error(`Studio Host ${agentResponse.status}`); if(!catalogResponse.ok)throw new Error(`Catalog ${catalogResponse.status}`);
      const [value,catalogValue]=await Promise.all([agentResponse.json() as Promise<{agents:Agent[]}>,catalogResponse.json() as Promise<Catalog>]);
      const shown=visibleAgents(value.agents) as Agent[];
      setAgents(shown); setCatalog(catalogValue); setHostOnline(true); setError("");
      setAgentId(current=>shown.some(agent=>agent.id===current)?current:(shown[0]?.id??""));
      const stateResponse=await fetch(`${API}/state`); if(stateResponse.ok){const saved=await stateResponse.json() as State; if(visibleParticipant({displayName:saved.opponent,participantId:saved.opponent})){setState(saved);if(saved.result)setPanel("move");}}
      try { const reviewerResponse=await fetch(`${API}/reviewers`); if(reviewerResponse.ok){ const reviewerValue=await reviewerResponse.json() as {reviewers:Reviewer[]}; setReviewers(visibleReviewers(reviewerValue.reviewers) as Reviewer[]); } } catch { /* reviewers optional */ }
    } catch(reason){ setHostOnline(false); setError(`Studio Host is not running. Launch the project once with Splendor Studio.cmd. ${reason instanceof Error?reason.message:String(reason)}`); }
  })()); },[]);

  function clearPending(nextPanel:GamePanel="table"){ setPendingTake(EMPTY_GEMS); setSelectedCard(null); setSelectedDeck(null); setContextActions([]); setPanel(nextPanel); }
  async function startGame(){
    setBusy(true);
    let sent=false;
    try {
      const body=humanStartBody(agentId,resolveSeat(seatChoice),seed);
      sent=true;
      const response=await fetch(`${API}/games`,{method:"POST",headers:{"Content-Type":"application/json"},body});
      const value=await response.json();
      if(!response.ok){sent=false;throw new Error(value.error??`Studio Host ${response.status}`);}
      setState(value);setShowReviewers(false);clearPending();setError("");setUncertain(false);
    } catch(reason){setUncertain(sent);setError(`${sent?"Start response unknown. Check the current session before starting another game. ":""}${reason instanceof Error?reason.message:String(reason)}`);}
    finally{setBusy(false);}
  }
  async function play(action:Action){
    if(busy||uncertain||!state||state.result||state.observation.public.current_player!==state.human_seat)return;
    setBusy(true);
    try {
      const response=await fetch(`${API}/action`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(action)});
      const value=await response.json();
      if(!response.ok)throw new Error(value.error??`Studio Host ${response.status}`);
      setState(value);clearPending(value.result?"move":"table");setError("");setUncertain(false);
    } catch(reason){setUncertain(true);setError(`Action outcome unknown. Check the current session; do not resend the move. ${reason instanceof Error?reason.message:String(reason)}`);}
    finally{setBusy(false);}
  }
  async function refreshSession(){
    setBusy(true);
    try{
      const response=await fetch(`${API}/state`);const value=await response.json();
      if(!response.ok)throw new Error(value.error??`Studio Host ${response.status}`);
      if(!visibleParticipant({displayName:value.opponent,participantId:value.opponent})){setState(null);setUncertain(false);setError("This session is not in the current Studio lineup.");return;}
      setState(value);clearPending(value.result?"move":"table");setUncertain(false);setError("");
    }catch(reason){setError(`Current session could not be confirmed. ${reason instanceof Error?reason.message:String(reason)}`);}
    finally{setBusy(false);}
  }
  async function retryBooking(){
    if(!state?.result)return;
    const sessionId=state.session_id;
    setBusy(true);
    try{
      const completion=await retryHumanBooking(fetch,API,sessionId);
      setState(current=>current?.session_id===sessionId?{...current,league_completion:completion}:current);
    }finally{setBusy(false);}
  }
  function openReplay(){ if(!state) return; window.location.assign(`${BASE_PATH}/replay?session=${encodeURIComponent(state.session_id)}`); }

  function changePendingGem(gem:GemName,delta:number){
    const candidate={...pendingTake,[gem]:Math.max(0,pendingTake[gem]+delta)};
    const isPrefix=takeActions.some(action=>TAKE_GEMS.every(color=>candidate[color]<=gemsOf(action.take)[color]));
    if(delta<0||isPrefix){ setPendingTake(candidate); setSelectedCard(null); setSelectedDeck(null); setContextActions([]); setPanel("table"); }
  }
  function openCard(tier:number,slot:number,cardId:number){
    const actions=(state?.legal_actions??[]).filter(action=>(action.type==="buy_market"||action.type==="reserve_market")&&action.tier===TIERS[tier]&&action.slot===slot);
    setSelectedCard({tier,slot,cardId}); setSelectedDeck(null); setContextActions(actions); setPendingTake(EMPTY_GEMS); setPanel("move");
  }
  function openDeck(tier:number){
    setSelectedCard(null); setSelectedDeck(tier); setContextActions((state?.legal_actions??[]).filter(action=>action.type==="reserve_deck"&&action.tier===TIERS[tier])); setPendingTake(EMPTY_GEMS); setPanel("move");
  }
  function openReserved(slot:number,cardId:number){
    setSelectedCard({tier:-1,slot,cardId}); setSelectedDeck(null); setContextActions((state?.legal_actions??[]).filter(action=>action.type==="buy_reserved"&&action.slot===slot)); setPendingTake(EMPTY_GEMS); setPanel("move");
  }

  const humanPlayer = state?.observation.public.players.find(item=>item.id===state.human_seat);
  const humanBonuses = humanPlayer?.bonuses;
  const confirmTake = exactTakeActions.length===1 ? exactTakeActions[0] : null;
  const pendingCount=TAKE_GEMS.reduce((sum,gem)=>sum+pendingTake[gem],0);
  const defaultReviewerId=defaultReviewerIdFor(reviewers,state?.observation.public.player_count??2);
  const yourTurn = state ? state.observation.public.current_player===state.human_seat : false;
  const controlsDisabled = busy||uncertain||!yourTurn||Boolean(state?.result);
  const needsReturn = pendingCount>0&&(exactTakeActions.length>1||(confirmTake!==null&&GEM_NAMES.some(gem=>actionReturns(confirmTake)[gem]>0)));
  const nobleActions = state?.legal_actions.filter(action=>action.type==="choose_noble")??[];
  const passAction = state?.legal_actions.find(action=>action.type==="pass");
  const takeHint = busy ? "Waiting for the opponent. Your move was sent once."
    : uncertain ? "Check the current session before making another move."
    : !yourTurn ? "Waiting for the opponent’s move."
    : nobleActions.length ? "Choose a noble to complete your turn."
    : passAction ? "No other move is available. Confirm to pass."
    : selectedCard ? "Review this card, then choose buy or reserve."
    : selectedDeck!==null ? "Reserve a hidden card from this deck."
    : pendingCount===0 ? "Choose a card or select gems from the bank."
    : needsReturn ? "Choose what to return in the Move panel."
    : confirmTake ? "Ready to take. Click a selected gem to remove it."
    : "Keep selecting gems, then confirm your take.";
  const cardIdle = !pendingCount&&!selectedCard&&selectedDeck===null;
  const turnLabel = state?.result ? "FINISHED" : uncertain ? "CHECK SESSION" : busy ? "THINKING…" : yourTurn ? "YOUR TURN" : "WAITING";

  return <main className={state?"human-studio human-cockpit bga-layout":"human-studio studio-page"} data-panel={panel}>
    {state?<header className="play-session-header">
      <div className="play-session-brand"><StudioBrand compact /><h1 className="play-session-title">Play Studio</h1><span className="session-ply">PLY <b>{state.ply}</b></span></div>
      <div className={`bga-action-banner ${state.result?"banner-finished":uncertain?"banner-uncertain":busy?"banner-busy":yourTurn?"banner-turn":"banner-waiting"}`} role="status">
        <strong className="banner-actor"><i aria-hidden="true" />{turnLabel}</strong>
        <span className="banner-hint">{state.result?`${humanResult(state.result,state.human_seat)} (${state.result.scores.join(" – ")})`:takeHint}</span>
      </div>
      <details className="studio-more play-session-menu">
        <summary>Table menu <span aria-hidden="true">⌄</span></summary>
        <div className="studio-more-menu">
          <small>THIS SESSION</small>
          <div className="human-session-parameters">Actual seat: {state.human_seat===0?"First (P0)":"Second (P1)"}<br/>Seed: <code>{state.seed??"—"}</code></div>
          <nav aria-label="Studio navigation"><Link href="/">Games</Link><Link href="/ratings">Ratings</Link><Link href="/league">League</Link></nav>
          <button disabled={busy||uncertain} onClick={()=>{setState(null);clearPending();setShowReviewers(false);}}>New game</button>
        </div>
      </details>
    </header>:<StudioHeader active="play" />}
    {error?<div className="error-banner" role="alert">{error}{uncertain?<button disabled={busy} onClick={()=>void refreshSession()}>Check current session</button>:null}</div>:null}
    {state?<section className="human-workspace bga-workspace">
      <div className="human-opponent" aria-label="Opponent resources">
        <div className="opponent-caption"><span>OPPONENT</span><strong title={state.opponent}>{state.opponent}</strong></div>
        <PlayerStateStrip playerView={state.observation as unknown as StripPlayerView} actor={state.observation.public.current_player} humanSeat={state.human_seat} omitSeat={state.human_seat} showZeroTokens />
      </div>

      <div className="human-resources" aria-label="Your resources">
        {humanPlayer?<PlayerHandCard player={humanPlayer} isActor={yourTurn&&!controlsDisabled} statusLabel={turnLabel}/>:null}
      </div>

      <nav className="human-panels" aria-label="Game panels">
        <button className="table-panel-button" aria-pressed={panel==="table"} aria-controls="play-table" onClick={()=>setPanel("table")}>Table</button>
        <button aria-pressed={panel==="move"} aria-controls="play-side-panel" onClick={()=>setPanel("move")}>{state.result?"Result":"Move"}{selectedCard||pendingCount||selectedDeck!==null?<i aria-label="Selection pending"/>:null}</button>
        <button aria-pressed={panel==="reserves"} aria-controls="play-side-panel" onClick={()=>setPanel("reserves")}>Reserves <b>{humanPlayer?.reserved_count??0}</b></button>
        <button aria-pressed={panel==="history"} aria-controls="play-side-panel" onClick={()=>setPanel("history")}>History</button>
      </nav>

      {/* The bank is a sibling of the switchable board, so it stays available in every panel. */}
      <div className="play-table-zone">
      <article className="human-board" id="play-table" aria-label="Card table">
        <div className="table-heading"><span>DEVELOPMENT MARKET</span><small>Net costs · after your discounts</small></div>
        <div className="bga-table-felt">
          <div className="human-market">{[2,1,0].map(tier=><div className="human-tier" key={tier}>
            <button type="button" className={`tier-deck tier-deck-${tier+1}`} aria-pressed={selectedDeck===tier} disabled={controlsDisabled||state.observation.public.deck_counts[tier]===0} onClick={()=>openDeck(tier)} aria-label={`Blind reserve from tier ${tier+1}, ${state.observation.public.deck_counts[tier]} cards left`}>
              <div className="deck-crest">
                <span className="deck-title">SPLENDOR</span>
                <span className="deck-tier-label">TIER {tier+1}</span>
              </div>
              <b className="deck-count">{state.observation.public.deck_counts[tier]}</b>
              <small className="deck-reserve-btn">RESERVE</small>
            </button>
            {state.observation.public.market[tier].map((cardId,slot)=>{
              const card=cardId==null?null:cards.get(cardId);
              return card?<DevelopmentCard card={card} interactive selected={selectedCard?.tier===tier&&selectedCard.slot===slot} affordable={state.legal_actions.some(action=>action.type==="buy_market"&&action.tier===TIERS[tier]&&action.slot===slot)} disabled={controlsDisabled} onClick={()=>openCard(tier,slot,cardId!)} slotLabel={`slot ${slot+1}`} discount={humanBonuses} key={slot}/>:<EmptyDevelopmentCard key={slot}/>;
            })}
          </div>)}</div>

          {/* Nobles require permanent discounts, not bank tokens. */}
          <section className="table-nobles" aria-label="Available nobles">
            <div className="nobles-header"><b>NOBLES</b><small title="Requirements use permanent card discounts">3 VP each</small></div>
            <div className="nobles-stack">
              {state.observation.public.nobles.map(id=>{
                const noble=nobles.get(id);
                const action=nobleActions.find(candidate=>candidate.noble===id);
                return noble?<NobleTile noble={noble} selectable={Boolean(action)} disabled={!action||controlsDisabled} onClick={()=>{if(action)void play(action);}} key={id}/>:null;
              })}
            </div>
          </section>
        </div>
      </article>
      <section className="human-bank" aria-label="Gem bank">
        <div className="bank-header"><b>BANK</b><small>Tap to take</small></div>
        <div className="bank-gems">{GEM_NAMES.map(gem=>{
          const canAdd=gem!=="gold"&&takeActions.some(action=>TAKE_GEMS.every(colour=>pendingTake[colour]+(colour===gem?1:0)<=gemsOf(action.take)[colour]));
          return <GemChip gem={gem} count={state.observation.public.bank[gem]} selected={pendingTake[gem]>0} selectedCount={pendingTake[gem]} disabled={controlsDisabled||!canAdd} onClick={()=>changePendingGem(gem,1)} key={gem}/>;
        })}</div>
        <small className="bank-gold-note">Gold from<br/>reserving</small>
      </section>
      </div>

      <aside className="human-actions" id="play-side-panel" ref={panelRef} tabIndex={-1} aria-label={panel==="reserves"?"Reserved cards":panel==="history"?"Public history":"Current move"}>
        {panel==="reserves"?<section className="reserves-panel">
          <span className="section-kicker">HELD CARDS</span><h2>Your reserve · {humanPlayer?.reserved_count??0}/3</h2>
          <p>Click your card to buy it. Reserve faces show printed costs.</p>
          <p className="holdings-summary">You: {humanPlayer?.purchased.length??0} developments · {humanPlayer?.nobles.length===1?"1 noble":`${humanPlayer?.nobles.length??0} nobles`}. {state.observation.public.players.filter(player=>player.id!==state.human_seat).map(player=><span key={player.id}>Opponent: {player.purchased.length} developments · {player.nobles.length===1?"1 noble":`${player.nobles.length} nobles`}.</span>)}</p>
          {state.observation.private.reserved.length?<div className="reserved-tray">{state.observation.private.reserved.map(reserved=>cards.has(reserved.card)?<DevelopmentCard card={cards.get(reserved.card)!} variant="mini" interactive affordable={state.legal_actions.some(action=>action.type==="buy_reserved"&&action.slot===reserved.slot)} disabled={controlsDisabled} onClick={()=>openReserved(reserved.slot,reserved.card)} slotLabel={`R${reserved.slot+1}`} key={reserved.slot}/>:null)}</div>:<p className="panel-empty">No cards reserved yet.</p>}
          <div className="human-score">{state.observation.public.players.map(item=>{
            const hasOpponentReserve=item.id!==state.human_seat&&item.reserved_count>0;
            if(!hasOpponentReserve&&!item.nobles.length)return null;
            return <div key={item.id}>
              {hasOpponentReserve?<OpponentReserve player={item} cards={cards}/>:null}
              {item.nobles.length?<div className="owned-nobles"><small>{item.id===state.human_seat?"Your":"Opponent's"} acquired nobles</small>{item.nobles.map(id=>nobles.has(id)?<NobleTile noble={nobles.get(id)!} owned key={id}/>:null)}</div>:null}
            </div>;
          })}</div>
          <div className="human-private"><span>PLAYER-VIEW ONLY</span><p>Public reserves are visible. Opponent blind reserves and deck order stay hidden.</p></div>
        </section>:panel==="history"?<section className="history-panel">
          <span className="section-kicker">PUBLIC HISTORY</span><h2>Recent moves</h2>
          {state.action_history.length?<ol>{state.action_history.toReversed().slice(0,10).map(item=><li className={item.actor===state.human_seat?"mine":"opponent"} key={item.ply}><small>PLY {item.ply}</small><div><HistoryText item={item} humanSeat={state.human_seat} cards={cards as ActionCatalog["cards"]} nobles={nobles as ActionCatalog["nobles"]}/></div></li>)}</ol>:<p>No moves yet. Confirmed moves will appear here.</p>}
        </section>:state.result?<div className="human-result">
          <strong>{humanResult(state.result,state.human_seat)}</strong><span>{state.result.scores.join(" – ")} · {state.result.reason.replaceAll("_"," ")}</span>
          {state.replay_ready?<><button disabled={busy} onClick={openReplay}>Open replay</button><button disabled={busy} onClick={()=>setShowReviewers(prev=>!prev)}>Review this game</button>
            {showReviewers?<div className="review-pick"><span className="section-kicker">CHOOSE A REVIEWER</span>{reviewers.map(reviewer=>{
              const supported=reviewerSupportsPlayerCount(reviewer,state.observation.public.player_count);
              return <button key={reviewer.id} disabled={!supported} onClick={()=>window.location.assign(`${BASE_PATH}/review?session=${encodeURIComponent(state.session_id)}&reviewer=${encodeURIComponent(reviewer.id)}`)}><strong>{reviewer.display_name}</strong><small>{reviewer.competitive_status==="rejected"?"Experimental · Formal promotion rejected":reviewer.competitive_status} · {reviewer.estimated_cost==="cpu"?"CPU":reviewer.estimated_cost}{reviewer.id===defaultReviewerId?" · recommended default":""}{supported?"":` · unavailable for ${state.observation.public.player_count}-player replays`}</small></button>;
            })}{reviewers.length===0?<small>No reviewers registered.</small>:null}</div>:null}
          </>:null}
          {state.replay_document_hash?<code>{state.replay_document_hash.slice(0,12)}…</code>:null}
          <HumanBookingPanel key={state.session_id} completion={state.league_completion} sessionId={state.session_id} humanSeat={state.human_seat} busy={busy} onRetry={()=>void retryBooking()}/>
        </div>:<section className="pending-panel">
          <span className="section-kicker">PENDING MOVE</span>
          <h2>{selectedCard?`Card #${selectedCard.cardId}`:selectedDeck!==null?`Tier ${selectedDeck+1} · blind reserve`:pendingCount?`Take ${pendingCount} gems`:nobleActions.length?"Choose a noble":passAction?"Pass required":"Your next move"}</h2>
          {selectedCard&&cards.has(selectedCard.cardId)?<div className="selected-card-preview"><DevelopmentCard card={cards.get(selectedCard.cardId)!} discount={humanBonuses}/></div>:null}
          {selectedDeck!==null?<p>The top card stays hidden until you reserve it. Gain gold if available.</p>:null}
          {contextActions.length?<div className="context-actions">{contextActions.map((action,index)=><button disabled={controlsDisabled} onClick={()=>void play(action)} key={index}><strong>{action.type==="buy_market"||action.type==="buy_reserved"?"Buy card":action.type==="reserve_market"?"Reserve card":"Blind reserve"}</strong>{GEM_NAMES.some(gem=>actionReturns(action)[gem]>0)?<span>Return <GemStrip gems={actionReturns(action)}/></span>:<small>{action.type.startsWith("reserve")?"Gain gold if available":"Pay with tokens and bonuses"}</small>}</button>)}</div>:null}
          {(selectedCard||selectedDeck!==null)&&!contextActions.length?<p>No legal buy or reserve for this selection. Choose another card or take gems.</p>:null}
          {needsReturn?<><p>Choose a legal return to confirm this take. Your resources stay visible.</p><div className="context-actions return-choices">{exactTakeActions.map((action,index)=><button disabled={controlsDisabled} onClick={()=>void play(action)} key={index}><strong>Return</strong><GemStrip gems={actionReturns(action)}/></button>)}</div></>:pendingCount?<p>{takeHint} Use the confirmation below.</p>:null}
          {cardIdle&&nobleActions.length?<div className="context-actions">{nobleActions.map((action,index)=><button disabled={controlsDisabled} onClick={()=>void play(action)} key={index}><strong>Choose noble #{String(action.noble)}</strong></button>)}</div>:null}
          {cardIdle&&!nobleActions.length?<div className="move-guide">
            <div><StudioGlyph name="gem" /><p><b>Take gems</b><span>Select in the bank, then confirm below.</span></p></div>
            <div><StudioGlyph name="layers" /><p><b>Buy or reserve</b><span>Choose a card to see your legal options.</span></p></div>
            <button type="button" className="reserve-shortcut" onClick={()=>setPanel("reserves")}>Your reserve <b>{humanPlayer?.reserved_count??0}/3</b><StudioGlyph name="arrow" /></button>
            <small>Nothing is sent until you confirm.</small>
          </div>:null}
          {(pendingCount||selectedCard||selectedDeck!==null)?<button className="cancel-move" disabled={busy} onClick={()=>clearPending()}>Cancel selection</button>:null}
        </section>}
      </aside>

      <footer className="human-dock" aria-label="Table controls">
        <section className="take-panel" aria-label="Take confirmation">
          <div className="take-selection"><h2>{state.result?"Game complete":pendingCount?`Take ${pendingCount}`:"Take gems"}</h2><div className="pending-gems">{TAKE_GEMS.filter(gem=>pendingTake[gem]>0).map(gem=><GemChip gem={gem} count={pendingTake[gem]} selected disabled={busy||uncertain} onClick={()=>changePendingGem(gem,-1)} key={gem}/>)}</div></div>
          <p role="status">{state.result?"Replay and booking details are in Result.":takeHint}</p>
          <div className="take-buttons">
            {state.result?<button className="confirm-move" onClick={()=>setPanel("move")}>View result</button>
              :nobleActions.length?<button className="confirm-move" disabled={controlsDisabled} onClick={()=>setPanel("move")}>Choose noble</button>
              :passAction?<button className="confirm-move" disabled={controlsDisabled} onClick={()=>void play(passAction)}>Pass turn</button>
              :needsReturn?<button className="confirm-move" disabled={controlsDisabled} onClick={()=>setPanel("move")}>Choose returns</button>
              :<button className="confirm-move" disabled={!confirmTake||controlsDisabled} onClick={()=>{if(confirmTake)void play(confirmTake);}}>Confirm take</button>}
            {pendingCount?<button className="cancel-move" disabled={busy} onClick={()=>clearPending()} aria-label="Cancel take" title="Cancel take">×</button>:null}
          </div>
        </section>
      </footer>
    </section>:null}
    {!state?<div className="studio-content play-setup">
      <div className="play-setup-story">
        <StudioIntro eyebrow="ONE CLICK · NO PORT SETUP" title="Your next move starts here."><p>Take a seat across from a registered agent. A classic table, a clear view of your resources, and every move saved for replay.</p></StudioIntro>
        <StudioTableArt />
        <div className="setup-features"><span><StudioGlyph name="gem" />Player-view only</span><span><StudioGlyph name="games" />Verified replays</span><span><StudioGlyph name="league" />Studio League</span></div>
      </div>
      <section className="human-connect">
        <div className="setup-status"><span className={`status-dot ${hostOnline?"":error?"offline":"pending"}`} />{hostOnline?"Studio Host ready":error?"Studio Host offline":"Connecting to Studio Host…"}</div>
        <span className="section-kicker">HUMAN VS AGENT</span><h2>Start a local game</h2>
        <p>Choose your opponent and take your seat.</p>
        {hostOnline && agents.length === 0 ? (
          <div className="roster-retired-badge">
            <strong>Lineup retired</strong>
            <span>Current Studio model roster is retired. Register a new engine model to start a game.</span>
          </div>
        ) : null}
        <label>Opponent<select value={agentId} onChange={event=>setAgentId(event.target.value)} disabled={!hostOnline||busy}>{agents.map(agent=><option value={agent.id} key={agent.id}>{agent.display_name}{agent.class==="checkpoint"?" · checkpoint":""}</option>)}</select></label>
        <label>Your seat<select value={seatChoice} onChange={event=>setSeatChoice(event.target.value)} disabled={!hostOnline||busy}><option value="random">Random</option><option value="first">First · P0</option><option value="second">Second · P1</option></select></label>
        <div className="setup-seed-row"><label>Game seed<input type="text" inputMode="numeric" value={seed} onChange={event=>setSeed(event.target.value)} disabled={!hostOnline||busy}/></label><button type="button" disabled={!hostOnline||busy} onClick={()=>setSeed(randomSeed())}>Randomize seed</button></div>
        <small>Exact unsigned 64-bit decimal; no rounding. Find the actual seat and seed in Table menu after starting.</small>
        <p className="rated-notice"><strong>Rated Studio League match</strong><br/>Your Elo may change. The finished game and its League booking are reported separately.</p>
        <button className="studio-primary" onClick={()=>void startGame()} disabled={!hostOnline||!agentId||busy||uncertain}>{busy?"Starting agent…":"Start new game"}</button>
        <small>{hostOnline?`${agents.length} registered agents ready`:`Double-click Splendor Studio.cmd in the project folder.`}</small>
      </section>
    </div>:null}
  </main>;
}
