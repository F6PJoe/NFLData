#!/usr/bin/env python3
"""Generate a self-contained preview of the two usage tables.

`usage_table.html` fetches its JSON at runtime, which needs a web server.
This bakes the data straight into a single file so the layout can be reviewed
by just opening it (or publishing it as an Artifact). Preview only -- the real
component stays in usage_table.html.

Usage:
    python build_preview.py --year 2025 --weeks 1-2
"""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

TEMPLATE = r"""<title>F6P Usage Tables</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap">

<style>
:root{
  --paper:#FAFBFC; --surface:#FFFFFF; --head:#EFF3F8;
  --ink:#151B24; --ink-2:#5A6675; --ink-3:#8794A4;
  --line:#DFE5EC; --line-2:#EDF1F6;
  --accent:#1F5FA8; --accent-soft:#E7F0FA;
  --bar:rgba(31,95,168,.16);
  --heat:#A65C0C;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#0D1218; --surface:#131A22; --head:#182029;
    --ink:#E3EAF3; --ink-2:#93A1B2; --ink-3:#6D7C8D;
    --line:#232D38; --line-2:#1B242E;
    --accent:#6FA6EA; --accent-soft:#17212D;
    --bar:rgba(111,166,234,.20);
    --heat:#D9922E;
  }
}
:root[data-theme="dark"]{
  --paper:#0D1218; --surface:#131A22; --head:#182029;
  --ink:#E3EAF3; --ink-2:#93A1B2; --ink-3:#6D7C8D;
  --line:#232D38; --line-2:#1B242E;
  --accent:#6FA6EA; --accent-soft:#17212D;
  --bar:rgba(111,166,234,.20);
  --heat:#D9922E;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font:400 15px/1.55 "IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1500px;margin:0 auto;padding:40px 24px 72px}
.masthead{border-bottom:2px solid var(--ink);padding-bottom:14px;margin-bottom:8px}
.eyebrow{
  font-family:"Barlow Condensed",sans-serif;font-weight:600;font-size:13px;
  letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin:0 0 4px
}
h1{
  font-family:"Barlow Condensed",sans-serif;font-weight:700;
  font-size:clamp(30px,4.4vw,46px);line-height:1.02;letter-spacing:-.01em;
  margin:0;text-wrap:balance
}
.standfirst{color:var(--ink-2);font-size:15px;max-width:64ch;margin:14px 0 0}
.standfirst code{
  font-family:"IBM Plex Sans",sans-serif;background:var(--accent-soft);
  color:var(--accent);padding:1px 6px;border-radius:4px;font-size:13px;font-weight:500
}

.post{margin-top:52px}
.post-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:4px}
.post-num{
  font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:13px;
  letter-spacing:.1em;color:var(--surface);background:var(--ink);
  padding:3px 9px;border-radius:3px
}
.post-head h2{
  font-family:"Barlow Condensed",sans-serif;font-weight:600;
  font-size:27px;letter-spacing:-.005em;margin:0
}
.post-sub{color:var(--ink-2);font-size:14px;margin:6px 0 18px;max-width:70ch}

.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:12px}
.grp{display:flex;align-items:center;gap:6px}
.grp label{
  font-family:"Barlow Condensed",sans-serif;font-weight:600;font-size:12px;
  letter-spacing:.11em;text-transform:uppercase;color:var(--ink-3)
}
.dash{color:var(--ink-3);font-size:13px}
select,input,button{
  font:500 13px/1 "IBM Plex Sans",sans-serif;color:var(--ink);
  background:var(--surface);border:1px solid var(--line);
  border-radius:6px;padding:7px 10px
}
input{min-width:190px}
button{cursor:pointer}
button:hover{border-color:var(--accent);color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.seg{display:flex;gap:4px}
.seg button.on{background:var(--accent);border-color:var(--accent);color:#fff}
.meta{
  font-family:"Barlow Condensed",sans-serif;font-weight:500;font-size:13px;
  letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);
  margin-bottom:8px;display:flex;gap:14px
}
.meta b{color:var(--ink);font-weight:600}

.scroll{
  overflow:auto;max-height:66vh;
  border:1px solid var(--line);border-radius:9px;background:var(--surface)
}
table{border-collapse:separate;border-spacing:0;width:100%;white-space:nowrap;
  font-variant-numeric:tabular-nums}
th,td{padding:8px 11px;text-align:right;border-bottom:1px solid var(--line-2)}
th{
  position:sticky;top:0;z-index:2;background:var(--head);cursor:pointer;
  font-family:"Barlow Condensed",sans-serif;font-weight:600;font-size:12px;
  letter-spacing:.09em;text-transform:uppercase;color:var(--ink-2);
  border-bottom:1px solid var(--line);user-select:none
}
th:hover{color:var(--accent)}
th.sorted{color:var(--accent)}
th.sorted::after{content:"▼";font-size:8px;margin-left:4px;vertical-align:middle}
th.sorted.asc::after{content:"▲"}
td{font-size:13.5px}
.txt{text-align:left}
td.name,th.name{position:sticky;left:0;background:var(--surface);z-index:1;
  font-weight:600;text-align:left}
th.name{z-index:3;background:var(--head)}
tbody tr:hover td{background:var(--accent-soft)}
tbody tr:hover td.name{background:var(--accent-soft)}
td.pos{color:var(--ink-3);font-size:11.5px;font-weight:600;letter-spacing:.05em}
/* Percentage cells carry a share bar -- these columns are all "portion of the
   team's whole", so the bar reads the role at a glance without another column. */
td.pct{
  color:var(--ink-2);font-size:12.5px;position:relative;
  background-image:linear-gradient(to right,var(--bar) var(--w,0%),transparent var(--w,0%));
  background-repeat:no-repeat
}
td.pct.hot{color:var(--heat);font-weight:600}
.empty{padding:30px;text-align:center;color:var(--ink-3)}
.foot{margin-top:44px;padding-top:16px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:13px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>

<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">Fantasy Six Pack &middot; Component preview</p>
    <h1>Usage Report Tables</h1>
  </header>
  <p class="standfirst">
    Both posts run off one component and one data file. The season view is
    aggregated in the browser from the weekly rows, so any week range works
    without a second upload. Real data below: <b>__RANGE__</b>, RB/WR/TE only.
    Sort any column, filter, and export what you're looking at.
  </p>

  <section class="post" id="post-weekly"></section>
  <section class="post" id="post-season"></section>

  <p class="foot">
    Percentage cells are shaded in proportion to their value. Team denominators
    ride along in the file, so every rate is recomputed from summed
    numerator &divide; denominator rather than averaging weekly percentages.
  </p>
</div>

<script>
var DATA = __DATA__;

var COLUMNS = [
  {key:"player",label:"Player",type:"name"},
  {key:"team",label:"Tm",type:"text"},
  {key:"pos",label:"Pos",type:"pos"},
  {key:"week",label:"Wk",type:"int",weeklyOnly:true},
  {key:"games",label:"G",type:"int",seasonOnly:true},
  {key:"snaps",label:"Snaps",type:"int"},
  {key:"snaps_pct",label:"Snap%",type:"pct"},
  {key:"routes",label:"Routes",type:"int"},
  {key:"routes_pct",label:"Rte%",type:"pct"},
  {key:"rush_att",label:"Rush",type:"int"},
  {key:"rush_att_pct",label:"Rush%",type:"pct"},
  {key:"targets",label:"Tgts",type:"int"},
  {key:"targets_pct",label:"Tgt%",type:"pct"},
  {key:"tprr",label:"TPRR",type:"pct"},
  {key:"catchable_tgts",label:"Catch",type:"int"},
  {key:"catchable_tgts_pct",label:"Catch%",type:"pct"},
  {key:"ez_tgts",label:"EZ",type:"int"},
  {key:"ez_tgts_pct",label:"EZ%",type:"pct"},
  {key:"inside5_rush",label:"I5",type:"int"},
  {key:"inside5_rush_pct",label:"I5%",type:"pct"},
  {key:"sdd_snaps",label:"SDD",type:"int"},
  {key:"sdd_snaps_pct",label:"SDD%",type:"pct"},
  {key:"ldd_snaps",label:"LDD",type:"int"},
  {key:"ldd_snaps_pct",label:"LDD%",type:"pct"},
  {key:"two_min_snaps",label:"2Min",type:"int"},
  {key:"two_min_snaps_pct",label:"2Min%",type:"pct"}
];

var SUM_COLS = ["snaps","routes","rush_att","targets","catchable_tgts","ez_tgts",
  "inside5_rush","sdd_snaps","ldd_snaps","two_min_snaps","team_snaps","team_routes",
  "team_targets","team_rush_att","team_two_min_snaps","team_ez_tgts",
  "team_inside5_rush","team_sdd_snaps","team_ldd_snaps"];

var RATES = {
  snaps_pct:["snaps","team_snaps"], routes_pct:["routes","team_routes"],
  rush_att_pct:["rush_att","team_rush_att"], targets_pct:["targets","team_targets"],
  ez_tgts_pct:["ez_tgts","team_ez_tgts"],
  inside5_rush_pct:["inside5_rush","team_inside5_rush"],
  sdd_snaps_pct:["sdd_snaps","team_sdd_snaps"],
  ldd_snaps_pct:["ldd_snaps","team_ldd_snaps"],
  two_min_snaps_pct:["two_min_snaps","team_two_min_snaps"],
  catchable_tgts_pct:["catchable_tgts","targets"],
  tprr:["targets","routes"]
};

var ROWS = DATA.rows.map(function(r){
  var o={}; for(var i=0;i<DATA.cols.length;i++){o[DATA.cols[i]]=r[i];} return o;
});
var WEEKS=[], TEAMS=[];
(function(){
  var w={},t={};
  ROWS.forEach(function(r){w[r.week]=1;t[r.team]=1;});
  WEEKS=Object.keys(w).map(Number).sort(function(a,b){return a-b;});
  TEAMS=Object.keys(t).sort();
})();

function el(tag,cls,text){
  var n=document.createElement(tag);
  if(cls){n.className=cls;}
  if(text!==undefined){n.textContent=text;}
  return n;
}
function opt(v,l,sel){
  var o=document.createElement("option");
  o.value=v; o.textContent=l; if(sel){o.selected=true;}
  return o;
}

function Grid(host, cfg){
  var view=cfg.view, pos="ALL", team="ALL", query="";
  var wkFrom=cfg.from, wkTo=cfg.to;
  var sortKey="snaps", sortAsc=false, visible=[], current=[];

  var head=el("div","post-head");
  head.appendChild(el("span","post-num",cfg.num));
  head.appendChild(el("h2",null,cfg.title));
  host.appendChild(head);
  host.appendChild(el("p","post-sub",cfg.sub));

  var ctl=el("div","controls");

  var gWeek=el("div","grp");
  gWeek.appendChild(el("label",null,view==="season"?"Range":"Week"));
  var selFrom=document.createElement("select"), selTo=document.createElement("select");
  WEEKS.forEach(function(w){
    selFrom.appendChild(opt(w,"Week "+w,w===wkFrom));
    selTo.appendChild(opt(w,"Week "+w,w===wkTo));
  });
  gWeek.appendChild(selFrom);
  gWeek.appendChild(el("span","dash","to"));
  gWeek.appendChild(selTo);
  ctl.appendChild(gWeek);

  var gPos=el("div","grp seg");
  ["ALL","RB","WR","TE"].forEach(function(p){
    var b=el("button",p==="ALL"?"on":null,p==="ALL"?"All":p);
    b.type="button";
    b.addEventListener("click",function(){
      pos=p;
      gPos.querySelectorAll("button").forEach(function(x){x.classList.toggle("on",x===b);});
      render();
    });
    gPos.appendChild(b);
  });
  ctl.appendChild(gPos);

  var gTeam=el("div","grp");
  gTeam.appendChild(el("label",null,"Team"));
  var selTeam=document.createElement("select");
  selTeam.appendChild(opt("ALL","All teams",true));
  TEAMS.forEach(function(t){selTeam.appendChild(opt(t,t));});
  gTeam.appendChild(selTeam);
  ctl.appendChild(gTeam);

  var gSearch=el("div","grp");
  var search=document.createElement("input");
  search.type="search"; search.placeholder="Search player…";
  gSearch.appendChild(search);
  ctl.appendChild(gSearch);

  var gCsv=el("div","grp");
  var csv=el("button",null,"Export CSV"); csv.type="button";
  gCsv.appendChild(csv); ctl.appendChild(gCsv);
  host.appendChild(ctl);

  var meta=el("div","meta");
  var mCount=el("b",null,""), mRange=el("span",null,"");
  meta.appendChild(mCount); meta.appendChild(mRange);
  host.appendChild(meta);

  var scroll=el("div","scroll");
  var table=document.createElement("table");
  var thead=document.createElement("thead"), hrow=document.createElement("tr");
  var tbody=document.createElement("tbody");
  thead.appendChild(hrow); table.appendChild(thead); table.appendChild(tbody);
  scroll.appendChild(table); host.appendChild(scroll);

  selFrom.addEventListener("change",function(){
    wkFrom=Number(this.value);
    if(wkTo<wkFrom){wkTo=wkFrom; selTo.value=String(wkTo);}
    render();
  });
  selTo.addEventListener("change",function(){
    wkTo=Number(this.value);
    if(wkFrom>wkTo){wkFrom=wkTo; selFrom.value=String(wkFrom);}
    render();
  });
  selTeam.addEventListener("change",function(){team=this.value;render();});
  search.addEventListener("input",function(){query=this.value.trim().toLowerCase();render();});
  csv.addEventListener("click",exportCsv);

  function aggregate(rows){
    var by={};
    rows.forEach(function(r){
      var a=by[r.player_id];
      if(!a){
        a=by[r.player_id]={player:r.player,pos:r.pos,team:r.team,games:0,_t:{}};
        SUM_COLS.forEach(function(c){a[c]=0;});
      }
      a.games+=1;
      a._t[r.team]=(a._t[r.team]||0)+1;
      SUM_COLS.forEach(function(c){a[c]+=(r[c]||0);});
    });
    return Object.keys(by).map(function(k){
      var a=by[k];
      a.team=Object.keys(a._t).sort(function(x,y){return a._t[y]-a._t[x];})[0];
      delete a._t;
      Object.keys(RATES).forEach(function(key){
        var n=a[RATES[key][0]], d=a[RATES[key][1]];
        a[key]=d?Math.round(n/d*1000)/10:0;
      });
      return a;
    });
  }

  function render(){
    visible=COLUMNS.filter(function(c){
      if(view==="season"&&c.weeklyOnly){return false;}
      if(view==="weekly"&&c.seasonOnly){return false;}
      return true;
    });
    var rows=ROWS.filter(function(r){
      if(r.week<wkFrom||r.week>wkTo){return false;}
      if(pos!=="ALL"&&r.pos!==pos){return false;}
      if(team!=="ALL"&&r.team!==team){return false;}
      if(query&&r.player.toLowerCase().indexOf(query)===-1){return false;}
      return true;
    });
    if(view==="season"){rows=aggregate(rows);}
    rows.sort(function(a,b){
      var x=a[sortKey],y=b[sortKey];
      if(typeof x==="string"||typeof y==="string"){
        x=String(x);y=String(y);
        return sortAsc?x.localeCompare(y):y.localeCompare(x);
      }
      return sortAsc?x-y:y-x;
    });
    current=rows;

    while(hrow.firstChild){hrow.removeChild(hrow.firstChild);}
    visible.forEach(function(c){
      var th=el("th",null,c.label);
      if(c.type==="name"){th.className="name";}
      else if(c.type==="text"||c.type==="pos"){th.className="txt";}
      if(c.key===sortKey){th.classList.add("sorted"); if(sortAsc){th.classList.add("asc");}}
      th.addEventListener("click",function(){
        if(sortKey===c.key){sortAsc=!sortAsc;}
        else{sortKey=c.key;sortAsc=(c.type==="name"||c.type==="text");}
        render();
      });
      hrow.appendChild(th);
    });

    while(tbody.firstChild){tbody.removeChild(tbody.firstChild);}
    if(!rows.length){
      var tr=document.createElement("tr"), td=el("td","empty","No players match those filters.");
      td.colSpan=visible.length; tr.appendChild(td); tbody.appendChild(tr);
    }else{
      var frag=document.createDocumentFragment();
      rows.forEach(function(r){
        var tr=document.createElement("tr");
        visible.forEach(function(c){
          var v=r[c.key], td=document.createElement("td");
          if(c.type==="name"){td.className="name";}
          else if(c.type==="text"){td.className="txt";}
          else if(c.type==="pos"){td.className="txt pos";}
          else if(c.type==="pct"){
            td.className="pct";
            var n=Number(v)||0;
            td.style.setProperty("--w",Math.max(0,Math.min(100,n))+"%");
            if(n>=70){td.classList.add("hot");}
          }
          td.textContent=(v===undefined||v===null)?"–":(c.type==="pct"?v+"%":String(v));
          tr.appendChild(td);
        });
        frag.appendChild(tr);
      });
      tbody.appendChild(frag);
    }

    mCount.textContent=rows.length.toLocaleString()+(view==="season"?" players":" player-weeks");
    mRange.textContent=(wkFrom===wkTo?"Week "+wkFrom:"Weeks "+wkFrom+"–"+wkTo);
  }

  function exportCsv(){
    var out=[visible.map(function(c){return c.label;}).join(",")];
    current.forEach(function(r){
      out.push(visible.map(function(c){
        var v=r[c.key];
        if(v===undefined||v===null){return "";}
        v=String(v);
        return /[",]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;
      }).join(","));
    });
    var a=document.createElement("a");
    a.href=URL.createObjectURL(new Blob([out.join("\n")],{type:"text/csv;charset=utf-8"}));
    a.download="f6p-usage-"+view+".csv";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  }

  render();
}

var LAST=WEEKS[WEEKS.length-1], FIRST=WEEKS[0];
Grid(document.getElementById("post-weekly"),{
  num:"POST 1", view:"weekly", from:LAST, to:LAST,
  title:"Weekly Usage",
  sub:"One row per player per week, every team at once — no team dropdown to step through. Opens on the most recent week; widen the range to compare weeks side by side."
});
Grid(document.getElementById("post-season"),{
  num:"POST 2", view:"season", from:FIRST, to:LAST,
  title:"Season-Long Usage",
  sub:"Totals per player, rebuilt in the browser from the same weekly rows — so the range is yours to choose, not a fixed full-season snapshot."
});
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--weeks", default="1-2")
    args = ap.parse_args()

    src = HERE / "data" / f"utilization_weekly_{args.year}_wk{args.weeks}.json"
    data = json.loads(src.read_text(encoding="utf-8"))

    weeks = sorted({r[data["cols"].index("week")] for r in data["rows"]})
    label = f"{args.year} weeks {weeks[0]}–{weeks[-1]}"

    html = (TEMPLATE
            .replace("__DATA__", json.dumps(data, separators=(",", ":")))
            .replace("__RANGE__", label))

    out = HERE / "usage_preview.html"
    out.write_text(html, encoding="utf-8")
    print(f"{out.name}  {out.stat().st_size/1024:.0f} KB  "
          f"({len(data['rows'])} rows, {label})")


if __name__ == "__main__":
    main()
