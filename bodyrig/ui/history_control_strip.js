(() => {
  const $ = (id) => document.getElementById(id);
  function text(id){ return ($(id)?.textContent || "").replace(/\s+/g," ").trim(); }
  function countHistory(){
    const host=$("historyList");
    if(!host) return 0;
    return [...host.children].filter((n)=>(n.textContent||"").trim()).length;
  }
  function setChip(id,state,active){
    const chip=$(id); if(!chip) return;
    const s=chip.querySelector(".chip-state"); if(s) s.textContent=state||"—";
    chip.classList.toggle("active",Boolean(active));
  }
  function refresh(){
    const person=text("personActive").replace(/^Person\s+/,"");
    const body=text("bodyActive").replace(/^Krop\s+/,"");
    const voice=text("voiceActive").replace(/^Stemme\s+/,"");
    const personality=text("personalityActive").replace(/^Personlighed\s+/,"");
    const count=countHistory();
    const activeCount=[body,voice,personality].filter((v)=>v&&v!=="—").length;
    setChip("historyControlActive",person&&person!=="—"?person:"Ingen aktiv",Boolean(person&&person!=="—"));
    setChip("historyControlRevisions",count ? String(count)+" post(er)" : "Ingen historik",count>0);
    setChip("historyControlComponents",String(activeCount)+"/3",activeCount===3);
    const next=$("historyControlNext");
    if(next){
      if(!person||person==="—") next.textContent="Ingen aktiv Person Revision.";
      else if(count===0) next.textContent="Aktiv revision findes, men historikken er tom.";
      else next.textContent=String(count)+" historikpost(er) · aktiv revision "+person+".";
    }
  }
  $("historyControlActive")?.addEventListener("click",()=>document.querySelector('.tab[data-tab="overview"]')?.click());
  $("historyControlRevisions")?.addEventListener("click",()=>$("historyList")?.scrollIntoView({behavior:"smooth",block:"start"}));
  $("historyControlComponents")?.addEventListener("click",()=>document.querySelector('.tab[data-tab="assemble"]')?.click());
  for(const id of ["historyList","personActive","bodyActive","voiceActive","personalityActive"]){
    const node=$(id);
    if(node) new MutationObserver(refresh).observe(node,{childList:true,characterData:true,subtree:true});
  }
  refresh();
})();