"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type Action = { type: string; [key: string]: unknown };
type Gems = { white:number; blue:number; green:number; red:number; black:number; gold:number };
type Agent = { id:string; display_name:string; class:string; policy_version:string; model_version:string|null; checkpoint_hash:string|null };
type State = {
  format:string; version:number; session_id:string; human_seat:number; opponent:string; ply:number;
  observation:{ viewer:number; public:{ current_player:number; phase:string; bank:Gems; deck_counts:number[]; market:Array<Array<number|null>>; nobles:number[]; players:Array<{id:number;tokens:Gems;bonuses:number[];prestige:number;reserved_count:number}> } };
  legal_actions:Action[];
  result:null|{scores:number[];ranks:number[];winners:number[];reason:string};
  replay_ready:boolean;
  replay_document_hash:string|null;
};

const API = "http://127.0.0.1:43120";
const gemNames = ["white","blue","green","red","black","gold"] as const;

function actionLabel(action:Action):string {
  const tier=typeof action.tier==="string"?` ${action.tier}`:"";
  const slot=typeof action.slot==="number"?` slot ${action.slot+1}`:"";
  if(action.type==="buy_market")return `Buy${tier}${slot}`;
  if(action.type==="buy_reserved")return `Buy reserved slot ${Number(action.slot)+1}`;
  if(action.type==="reserve_market")return `Reserve${tier}${slot}`;
  if(action.type==="reserve_deck")return `Reserve from${tier} deck`;
  if(action.type==="choose_noble")return `Choose noble #${action.noble}`;
  if(action.type==="pass")return "Pass";
  if(action.type==="take_tokens"&&action.take&&typeof action.take==="object"){
    const take=action.take as Record<string,number>; const picked=gemNames.filter(gem=>(take[gem]??0)>0).map(gem=>`${gem[0].toUpperCase()}×${take[gem]}`).join(" ");
    return `Take ${picked}`;
  }
  return action.type.replaceAll("_"," ");
}

export default function HumanPlayPage() {
  const [state,setState] = useState<State|null>(null);
  const [agents,setAgents] = useState<Agent[]>([]);
  const [agentId,setAgentId] = useState("m07-champion");
  const [humanSeat,setHumanSeat] = useState(0);
  const [seed,setSeed] = useState(()=>Math.floor(Date.now()/1000));
  const [hostOnline,setHostOnline] = useState(false);
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);

  useEffect(()=>{ queueMicrotask(()=>void (async()=>{
    try {
      const response=await fetch(`${API}/agents`); if(!response.ok)throw new Error(`Studio Host ${response.status}`);
      const value=await response.json() as {agents:Agent[]}; setAgents(value.agents); setHostOnline(true); setError("");
      setAgentId(current=>value.agents.some(agent=>agent.id===current)?current:(value.agents[0]?.id??""));
      const stateResponse=await fetch(`${API}/state`); if(stateResponse.ok)setState(await stateResponse.json());
    } catch(reason){ setHostOnline(false); setError(`Studio Host is not running. Launch the project once with Start Splendor Studio.cmd. ${reason instanceof Error?reason.message:String(reason)}`); }
  })()); },[]);
  async function startGame(){ setBusy(true); try { const response=await fetch(`${API}/games`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({agent_id:agentId,human_seat:humanSeat,seed})}); const value=await response.json(); if(!response.ok)throw new Error(value.error??`Studio Host ${response.status}`); setState(value); setError(""); } catch(reason){ setError(reason instanceof Error?reason.message:String(reason)); } finally{setBusy(false);} }
  async function play(action:Action){ setBusy(true); try { const response=await fetch(`${API}/action`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(action)}); const value=await response.json(); if(!response.ok) throw new Error(value.error??`Studio Host ${response.status}`); setState(value); setError(""); } catch(reason){ setError(reason instanceof Error?reason.message:String(reason)); } finally { setBusy(false); } }
  async function openReplay(){ setBusy(true); try { const response=await fetch(`${API}/archive`); const value=await response.json(); if(!response.ok) throw new Error(value.error??`Studio Host ${response.status}`); sessionStorage.setItem("effective-splendor-human-replay",JSON.stringify(value)); window.location.assign("/?humanReplay=1"); } catch(reason){ setError(reason instanceof Error?reason.message:String(reason)); setBusy(false); } }
  return <main className="human-studio">
    <header className="human-topbar"><div><span className="section-kicker">LOCAL 1V1 · ONE-CLICK HOST</span><h1>Human Play Studio</h1></div><div className="human-status"><span className={`status-dot ${hostOnline?"":"offline"}`} />{state?`${state.opponent} · ply ${state.ply}`:hostOnline?"Studio Host ready":"Studio Host offline"}</div><nav><Link href="/">Replay Studio</Link><Link href="/ratings">Ratings</Link>{state&&<button onClick={()=>setState(null)}>New game</button>}</nav></header>
    {error&&<div className="error-banner" role="alert">{error}</div>}
    {state&&<section className="human-workspace">
      <article className="human-board">
        <div className="human-score">{state.observation.public.players.map(player=><div className={player.id===state.human_seat?"you":""} key={player.id}><span>{player.id===state.human_seat?"YOU":"OPPONENT"}</span><strong>{player.prestige}<small> VP</small></strong><small>{player.reserved_count} reserved</small></div>)}</div>
        <div className="human-bank"><span>BANK</span>{gemNames.map(gem=><i className={`token-${gem}`} key={gem}>{gem[0].toUpperCase()} <b>{state.observation.public.bank[gem]}</b></i>)}</div>
        <div className="human-market">{[2,1,0].map(tier=><div className="human-tier" key={tier}><span>TIER {tier+1}<small>{state.observation.public.deck_counts[tier]} deck</small></span>{state.observation.public.market[tier].map((card,slot)=><button disabled={card==null||busy} onClick={()=>{const action=state.legal_actions.find(item=>item.type==="buy_market"&&item.tier===["One","Two","Three"][tier]&&item.slot===slot); if(action)void play(action);}} key={slot}><b>{card==null?"—":`#${card}`}</b><small>{state.legal_actions.some(item=>item.type==="buy_market"&&item.tier===["One","Two","Three"][tier]&&item.slot===slot)?"BUY":"market"}</small></button>)}</div>)}</div>
        <div className="human-private"><span>PLAYER-VIEW ONLY</span><p>The browser receives your Observation and legal actions only. Deck order and the opponent&apos;s blind reserve never cross the Host boundary.</p></div>
      </article>
      <aside className="human-actions"><div><span className="section-kicker">LEGAL ACTIONS</span><h2>{state.result?"Game complete":state.observation.public.current_player===state.human_seat?"Choose your move":"Opponent thinking"}</h2></div>{state.result?<div className="human-result"><strong>{state.result.winners.includes(state.human_seat)?"VICTORY":"DEFEAT"}</strong><span>{state.result.scores.join(" – ")} · {state.result.reason.replaceAll("_"," ")}</span>{state.replay_ready&&<button disabled={busy} onClick={()=>void openReplay()}>Open verified game in Replay Studio →</button>}{state.replay_document_hash&&<code>{state.replay_document_hash.slice(0,12)}…</code>}</div>:<div className="human-action-list">{state.legal_actions.map((action,index)=><button disabled={busy} onClick={()=>void play(action)} key={`${action.type}-${index}`}><span>{actionLabel(action)}</span><small>{action.type.replaceAll("_"," ")}</small></button>)}</div>}</aside>
    </section>}
    {!state&&<section className="human-connect"><span>ONE CLICK · NO PORT SETUP</span><h2>Start a local game</h2><p>The Studio Host owns the agent process. Choose any registered baseline, search agent or GPU checkpoint and start immediately.</p><label>Opponent<select value={agentId} onChange={event=>setAgentId(event.target.value)} disabled={!hostOnline||busy}>{agents.map(agent=><option value={agent.id} key={agent.id}>{agent.display_name}{agent.class==="checkpoint"?" · checkpoint":""}</option>)}</select></label><label>Your seat<select value={humanSeat} onChange={event=>setHumanSeat(Number(event.target.value))} disabled={!hostOnline||busy}><option value={0}>P0 · first</option><option value={1}>P1 · second</option></select></label><label>Game seed<input type="number" min="0" value={seed} onChange={event=>setSeed(Number(event.target.value))} disabled={!hostOnline||busy}/></label><button onClick={()=>void startGame()} disabled={!hostOnline||!agentId||busy}>{busy?"Starting agent…":"Start new game"}</button><small>{hostOnline?`${agents.length} registered agents ready`:`Double-click Start Splendor Studio.cmd in the project folder.`}</small></section>}
  </main>;
}
