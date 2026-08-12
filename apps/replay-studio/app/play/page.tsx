"use client";

import Link from "next/link";
import { useState } from "react";

type Action = { type: string; [key: string]: unknown };
type Gems = { white:number; blue:number; green:number; red:number; black:number; gold:number };
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
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  async function refresh(){ try { const response=await fetch(`${API}/state`); if(!response.ok) throw new Error(`server ${response.status}`); setState(await response.json()); setError(""); } catch(reason){ setError(`Start the local human-play server on port 43120. ${reason instanceof Error?reason.message:String(reason)}`); } }
  async function play(action:Action){ setBusy(true); try { const response=await fetch(`${API}/action`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(action)}); const value=await response.json(); if(!response.ok) throw new Error(value.error??`server ${response.status}`); setState(value); setError(""); } catch(reason){ setError(reason instanceof Error?reason.message:String(reason)); } finally { setBusy(false); } }
  async function openReplay(){ setBusy(true); try { const response=await fetch(`${API}/archive`); const value=await response.json(); if(!response.ok) throw new Error(value.error??`server ${response.status}`); sessionStorage.setItem("effective-splendor-human-replay",JSON.stringify(value)); window.location.assign("/?humanReplay=1"); } catch(reason){ setError(reason instanceof Error?reason.message:String(reason)); setBusy(false); } }
  return <main className="human-studio">
    <header className="human-topbar"><div><span className="section-kicker">M20 · LOCAL 1V1</span><h1>Human Play Studio</h1></div><div className="human-status"><span className={`status-dot ${state?"":"offline"}`} />{state?`${state.opponent} · ply ${state.ply}`:"server offline"}</div><nav><Link href="/">Replay Studio</Link><Link href="/ratings">Ratings</Link><button onClick={()=>void refresh()}>Connect</button></nav></header>
    {error&&<div className="error-banner" role="alert">{error}<code>cargo run -p splendor-cli -- human-play-server --seed 200001 --human-seat 0 --opponent m07 --port 43120</code></div>}
    {state&&<section className="human-workspace">
      <article className="human-board">
        <div className="human-score">{state.observation.public.players.map(player=><div className={player.id===state.human_seat?"you":""} key={player.id}><span>{player.id===state.human_seat?"YOU":"OPPONENT"}</span><strong>{player.prestige}<small> VP</small></strong><small>{player.reserved_count} reserved</small></div>)}</div>
        <div className="human-bank"><span>BANK</span>{gemNames.map(gem=><i className={`token-${gem}`} key={gem}>{gem[0].toUpperCase()} <b>{state.observation.public.bank[gem]}</b></i>)}</div>
        <div className="human-market">{[2,1,0].map(tier=><div className="human-tier" key={tier}><span>TIER {tier+1}<small>{state.observation.public.deck_counts[tier]} deck</small></span>{state.observation.public.market[tier].map((card,slot)=><button disabled={card==null||busy} onClick={()=>{const action=state.legal_actions.find(item=>item.type==="buy_market"&&item.tier===["One","Two","Three"][tier]&&item.slot===slot); if(action)void play(action);}} key={slot}><b>{card==null?"—":`#${card}`}</b><small>{state.legal_actions.some(item=>item.type==="buy_market"&&item.tier===["One","Two","Three"][tier]&&item.slot===slot)?"BUY":"market"}</small></button>)}</div>)}</div>
        <div className="human-private"><span>PLAYER-VIEW ONLY</span><p>The browser receives your Observation and legal actions only. Deck order and the opponent&apos;s blind reserve never cross the server boundary.</p></div>
      </article>
      <aside className="human-actions"><div><span className="section-kicker">LEGAL ACTIONS</span><h2>{state.result?"Game complete":state.observation.public.current_player===state.human_seat?"Choose your move":"Opponent thinking"}</h2></div>{state.result?<div className="human-result"><strong>{state.result.winners.includes(state.human_seat)?"VICTORY":"DEFEAT"}</strong><span>{state.result.scores.join(" – ")} · {state.result.reason.replaceAll("_"," ")}</span>{state.replay_ready&&<button disabled={busy} onClick={()=>void openReplay()}>Open verified game in Replay Studio →</button>}{state.replay_document_hash&&<code>{state.replay_document_hash.slice(0,12)}…</code>}</div>:<div className="human-action-list">{state.legal_actions.map((action,index)=><button disabled={busy} onClick={()=>void play(action)} key={`${action.type}-${index}`}><span>{actionLabel(action)}</span><small>{action.type.replaceAll("_"," ")}</small></button>)}</div>}</aside>
    </section>}
    {!state&&<section className="human-connect"><span>PLAYER-VIEW ONLY</span><h2>Connect to a local game</h2><p>Start the Rust session server, then connect. Only your Observation and legal actions enter this page.</p><button onClick={()=>void refresh()}>Connect to port 43120</button><small>LEGAL ACTIONS are rendered after connection.</small></section>}
  </main>;
}
