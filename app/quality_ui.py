from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.pantry_ui import STYLE, TOKEN_JS, navigation


router = APIRouter(tags=["Data Quality UI"])

HTML = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>数据质量 · Food Assistant</title><style>{STYLE}</style></head><body><header><div><h1>数据质量</h1><span class="muted">只读检查本地库存、消耗确认与购物清单完整度</span></div>{navigation("quality")}</header><main><div id="error" class="error"></div><div id="success" class="success" role="status"></div><section id="summary" class="grid"></section><section class="panel"><h2>处理入口</h2><p>本页不直接修改数据。</p><div class="actions"><a href="/pantry">管理库存</a><a href="/consumption">查看消耗确认</a><a href="/shopping">查看购物清单</a></div></section></main><script>{TOKEN_JS}
document.querySelector('#token').value=token();const labels={{inventory_total:'库存总数',inventory_unknown_quantity:'数量未知',inventory_missing_unit:'单位缺失',inventory_unrecognized_unit:'单位无法识别',duplicate_normalized_names:'规范化名称重复组',pending_consumption_reviews:'待确认消耗',ambiguous_consumption_matches:'消耗匹配歧义',unmatched_consumption_ingredients:'未匹配食材',incompatible_unit_matches:'单位不兼容',active_shopping_items:'待购买项目',shopping_items_missing_quantity:'购物数量未定',shopping_items_missing_unit:'购物单位缺失',recent_adjustment_count:'近 30 天库存调整'}};async function load(){{clearMessages();try{{const data=await api('/api/v1/data-quality/summary');document.querySelector('#summary').innerHTML=Object.entries(labels).map(([key,label])=>`<article class="card"><div class="muted">${{label}}</div><div class="summary">${{data[key]??0}}</div></article>`).join('');success('检查完成：'+new Date(data.latest_checked_at).toLocaleString())}}catch(e){{fail(e)}}}}load();</script></body></html>'''


@router.get("/quality", response_class=HTMLResponse, include_in_schema=False)
@router.get("/quality/", response_class=HTMLResponse, include_in_schema=False)
def page() -> HTMLResponse:
    return HTMLResponse(HTML)
