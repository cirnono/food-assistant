from __future__ import annotations

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.cooking_sessions import HOME_ASSISTANT_KITCHEN_URL
from app.pantry_ui import STYLE, TOKEN_JS


router = APIRouter(tags=["Cooking UI"])


@router.get("/cook", response_class=HTMLResponse, include_in_schema=False)
@router.get("/cook/", response_class=HTMLResponse, include_in_schema=False)
def cooking_page() -> HTMLResponse:
    return HTMLResponse(COOKING_HTML)


KITCHEN_LINK = escape(HOME_ASSISTANT_KITCHEN_URL, quote=True)


COOKING_HTML = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>分步烹饪 · Food Assistant</title><style>{STYLE}
.cook-step{{font-size:clamp(28px,4vw,56px);line-height:1.45;min-height:180px;display:flex;align-items:center}}button{{min-height:48px}}.timer-time{{font-size:32px;font-variant-numeric:tabular-nums}}.timer-overdue{{background:#f7e5e3;border-color:var(--danger)}}.ingredients label{{display:block;padding:10px;border-bottom:1px solid var(--border)}}.ingredients input{{width:auto;margin-right:10px}}.split{{display:grid;grid-template-columns:minmax(0,2fr) minmax(280px,1fr);gap:16px}}@media(max-width:800px){{.split{{grid-template-columns:1fr}}}}
</style></head><body><header><div><h1>分步烹饪</h1><span class="muted">步骤与计时器会自动恢复</span></div><div><input id="token" type="password" placeholder="Food Assistant API Token"><button onclick="saveToken()">保存令牌</button>{f'<a href="{KITCHEN_LINK}">返回厨房面板</a>' if KITCHEN_LINK else ''}</div></header><main><div id="error" class="error"></div><div id="idle" class="panel" hidden><h2>还没有开始做饭</h2><div id="recommendation" class="muted">正在读取当前推荐……</div><button class="primary" id="start" onclick="startCooking()">开始做饭</button></div><div id="active" hidden><div class="split"><section><div class="panel"><h1 id="recipeName"></h1><p id="progress" class="muted"></p><div id="step" class="cook-step"></div><div class="actions"><button onclick="sessionAction('previous-step')">上一步</button><button class="primary" onclick="sessionAction('next-step')">下一步</button><button class="success" onclick="finishCooking()">完成烹饪</button><button class="danger" onclick="cancelCooking()">取消烹饪</button></div></div><section class="panel ingredients"><h2>食材</h2><div id="ingredients"></div></section></section><aside><section class="panel"><h2>计时器</h2><div class="actions">${{[1,3,5,10,15,30].map(m=>`<button onclick="quickTimer(${{m}})">${{m}} 分钟</button>`).join('')}}</div><p><input id="timerLabel" placeholder="标签，例如：焖煮"></p><div class="toolbar"><input id="timerMinutes" type="number" min="0" placeholder="分钟"><input id="timerSeconds" type="number" min="0" max="59" placeholder="秒"><button onclick="customTimer()">添加</button></div><div id="timers"></div></section></aside></div></div></main><script>{TOKEN_JS}
document.querySelector('#token').value=token();let session=null;let selected=null;let alerted=new Set();
function esc(value){{return String(value??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]))}}
function body(extra={{}}){{return JSON.stringify({{owner:'household',confirm_session_id:session.id,...extra}})}}
async function load(){{try{{const active=await api('/api/v1/cooking-sessions/active?owner=household');if(active){{session=active;renderSession()}}else{{document.querySelector('#active').hidden=true;document.querySelector('#idle').hidden=false;const state=await api('/api/v1/home-assistant/state?owner=household');selected=state.selected_recipe;document.querySelector('#recommendation').textContent=selected?`当前推荐：${{selected.name}}`:'当前没有可用推荐';document.querySelector('#start').disabled=!selected}}catch(e){{fail(e)}}}}
function renderSession(){{document.querySelector('#idle').hidden=true;document.querySelector('#active').hidden=false;document.querySelector('#recipeName').textContent=session.recipe_name;const steps=session.recipe.instructions;document.querySelector('#progress').textContent=`步骤 ${{session.current_step_index+1}} / ${{steps.length}}`;const current=steps[session.current_step_index];document.querySelector('#step').textContent=(current.title?current.title+'：':'')+current.text;const checked=new Set(session.checked_ingredient_indexes);document.querySelector('#ingredients').innerHTML=session.recipe.ingredients.map((x,i)=>`<label><input type="checkbox" ${{checked.has(i)?'checked':''}} onchange="toggleIngredient(${{i}})">${{esc(x.display||x.name)}} ${{esc(x.quantity)}} ${{esc(x.unit)}}</label>`).join('');renderTimers(session.timers)}}
async function startCooking(){{try{{session=await api('/api/v1/cooking-sessions/start',{{method:'POST',body:JSON.stringify({{owner:'household',mealie_slug:selected.slug,confirm_slug:selected.slug,servings:null}})}});renderSession()}}catch(e){{fail(e)}}}}
async function sessionAction(action,extra={{}}){{try{{session=await api(`/api/v1/cooking-sessions/${{session.id}}/${{action}}`,{{method:'POST',body:body(extra)}});renderSession()}}catch(e){{fail(e)}}}}
async function toggleIngredient(index){{await sessionAction('toggle-ingredient',{{ingredient_index:index}})}}
async function finishCooking(){{if(confirm('确认完成烹饪并写入做饭历史吗？'))await sessionAction('finish',{{select_next:true}}).then(()=>load())}}
async function cancelCooking(){{if(confirm('确认取消本次烹饪吗？'))await sessionAction('cancel').then(()=>load())}}
async function addTimer(label,seconds){{try{{await api(`/api/v1/cooking-sessions/${{session.id}}/timers`,{{method:'POST',body:body({{label,duration_seconds:seconds,start_immediately:true}})}});await sync()}}catch(e){{fail(e)}}}}
function quickTimer(minutes){{addTimer(`${{minutes}} 分钟`,minutes*60)}}function customTimer(){{const seconds=Number(document.querySelector('#timerMinutes').value||0)*60+Number(document.querySelector('#timerSeconds').value||0);addTimer(document.querySelector('#timerLabel').value||'计时器',seconds)}}
async function timerAction(id,action){{try{{await api(`/api/v1/cooking-sessions/${{session.id}}/timers/${{id}}/${{action}}`,{{method:'POST',body:body()}});await sync()}}catch(e){{fail(e)}}}}
function remaining(t){{if(t.state==='running'&&t.deadline_at)return Math.max(0,Math.ceil((new Date(t.deadline_at)-Date.now())/1000));return t.remaining_seconds||0}}function fmt(s){{return `${{String(Math.floor(s/60)).padStart(2,'0')}}:${{String(s%60).padStart(2,'0')}}`}}
function beep(){{try{{const c=new AudioContext(),o=c.createOscillator();o.connect(c.destination);o.start();o.stop(c.currentTime+.25)}}catch{{}}}}
function renderTimers(timers){{document.querySelector('#timers').innerHTML=timers.filter(t=>t.state!=='cancelled').map(t=>{{const left=remaining(t),over=t.state==='finished'||left===0;if(over&&!alerted.has(t.id)){{alerted.add(t.id);beep()}}return `<article class="card ${{over?'timer-overdue':''}}"><strong>${{esc(t.label)}}</strong><div class="timer-time">${{over?'时间到！':fmt(left)}}</div><div class="actions">${{t.state==='running'?`<button onclick="timerAction(${{t.id}},'pause')">暂停</button>`:''}}${{t.state==='paused'?`<button onclick="timerAction(${{t.id}},'resume')">恢复</button>`:''}}${{!over?`<button onclick="timerAction(${{t.id}},'finish')">完成</button><button onclick="timerAction(${{t.id}},'cancel')">取消</button>`:''}}</div></article>`}}).join('')}}
async function sync(){{if(!session)return;try{{const state=await api('/api/v1/cooking-sessions/active-state?owner=household');if(state.status==='idle'){{session=null;return load()}}session.timers=state.timers;session.current_step_index=state.session.current_step_index;renderSession()}}catch(e){{fail(e)}}}}setInterval(()=>session&&renderTimers(session.timers),1000);setInterval(sync,10000);load();
</script></body></html>'''
