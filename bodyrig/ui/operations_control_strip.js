(() => {
  const $ = (id) => document.getElementById(id);
  function text(id){ return ($(id)?.textContent || "").replace(/\s+/g," ").trim(); }
  function setChip(id,state,active){
    const chip=$(id); if(!chip) return;
    const s=chip.querySelector(".chip-state"); if(s) s.textContent=state||"—";
    chip.classList.toggle("active",Boolean(active));
  }
  function badState(value){ return /fejl|failed|stale|unhealthy|blokeret|blocked|ukendt|unknown|kræver|required/i.test(value); }
  function countRendered(id){
    const host=$(id); if(!host) return 0;
    return [...host.children].filter((n)=>(n.textContent||"").trim()).length;
  }
  function refresh(){
    const health=text("operatorSummary");
    const attention=text("operatorAttentionBadge");
    const jobs=text("operatorJobsStatus");
    const launches=text("operatorLaunchesStatus");
    const twin=text("operator-digital-twin-badge");
    const twinSummary=text("operator-digital-twin-summary");
    const attentionCount=countRendered("operatorAttentionItems");

    setChip("operationsControlHealth",health||"Ukendt",Boolean(health&&!badState(health)));
    setChip("operationsControlAttention",attentionCount?String(attentionCount)+" handling(er)":(attention||"Ingen"),attentionCount===0&&!badState(attention));
    setChip("operationsControlExecution",(jobs||"Jobs")+" · "+(launches||"Launches"),!badState((jobs||"")+" "+(launches||"")));
    setChip("operationsControlTwin",twin||"Ukendt",/klar|ready|pass|aktiv/i.test((twin||"")+" "+(twinSummary||"")));

    const next=$("operationsControlNext");
    if(!next) return;
    if(attentionCount>0) next.textContent=String(attentionCount)+" operator-handling(er) kræver opmærksomhed.";
    else if(badState(health)) next.textContent=health||"Service-health kræver opmærksomhed.";
    else if(badState(twin)) next.textContent=twinSummary||("Digital Twin · "+(twin||"ukendt"));
    else if(badState((jobs||"")+" "+(launches||""))) next.textContent="Kontrollér aktive jobs eller operator launches.";
    else next.textContent="Drift ser stabil ud · ingen prioriteret blocker.";
  }

  $("operationsControlHealth")?.addEventListener("click",()=>$("operatorRefresh")?.scrollIntoView({behavior:"smooth",block:"center"}));
  $("operationsControlAttention")?.addEventListener("click",()=>$("operatorAttentionItems")?.scrollIntoView({behavior:"smooth",block:"start"}));
  $("operationsControlExecution")?.addEventListener("click",()=>$("operatorJobs")?.scrollIntoView({behavior:"smooth",block:"start"}));
  $("operationsControlTwin")?.addEventListener("click",()=>$("operator-digital-twin-stages")?.scrollIntoView({behavior:"smooth",block:"start"}));

  for(const id of [
    "operatorSummary","operatorAttentionBadge","operatorAttentionItems",
    "operatorJobsStatus","operatorLaunchesStatus","operator-digital-twin-badge","operator-digital-twin-summary"
  ]){
    const node=$(id);
    if(node) new MutationObserver(refresh).observe(node,{childList:true,characterData:true,subtree:true,attributes:true});
  }
  refresh();
})();