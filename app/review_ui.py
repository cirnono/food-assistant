from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(
    tags=["Review UI"],
)


@router.get(
    "/review",
    response_class=HTMLResponse,
    include_in_schema=False,
)
@router.get(
    "/review/",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def review_page() -> HTMLResponse:
    return HTMLResponse(
        REVIEW_HTML
    )


REVIEW_HTML = r'''
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta
    name="viewport"
    content="width=device-width, initial-scale=1"
  >
  <title>Food Assistant 审核中心</title>

  <style>
    :root {
      color-scheme: light;
      --background: #f5f1e8;
      --panel: #fffdf8;
      --panel-alt: #f9f5ec;
      --border: #ddd3c2;
      --text: #312b23;
      --muted: #756b5d;
      --primary: #8a5a2b;
      --primary-hover: #70471f;
      --success: #23643f;
      --warning: #956600;
      --danger: #9b302d;
      --shadow: 0 8px 28px rgba(76, 58, 35, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background: var(--background);
      color: var(--text);
      font-family:
        Inter,
        "Noto Sans SC",
        "Microsoft YaHei",
        system-ui,
        sans-serif;
    }

    button,
    input,
    textarea,
    select {
      font: inherit;
    }

    button {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 9px 13px;
      background: white;
      color: var(--text);
      cursor: pointer;
    }

    button:hover:not(:disabled) {
      border-color: var(--primary);
    }

    button:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }

    button.primary {
      background: var(--primary);
      border-color: var(--primary);
      color: white;
    }

    button.primary:hover:not(:disabled) {
      background: var(--primary-hover);
    }

    button.success {
      background: var(--success);
      border-color: var(--success);
      color: white;
    }

    button.danger {
      background: var(--danger);
      border-color: var(--danger);
      color: white;
    }

    input,
    textarea,
    select {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: white;
      color: var(--text);
      padding: 9px 10px;
    }

    textarea {
      min-height: 92px;
      resize: vertical;
      line-height: 1.55;
    }

    input:focus,
    textarea:focus,
    select:focus {
      outline: 2px solid rgba(138, 90, 43, 0.18);
      border-color: var(--primary);
    }

    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 16px 22px;
      background: var(--panel);
      border-bottom: 1px solid var(--border);
    }

    .topbar h1 {
      margin: 0;
      font-size: 21px;
    }

    .topbar p {
      margin: 3px 0 0;
      color: var(--muted);
      font-size: 13px;
    }

    .layout {
      min-height: 0;
      display: grid;
      grid-template-columns: 330px minmax(0, 1fr);
    }

    .sidebar {
      min-height: 0;
      padding: 16px;
      border-right: 1px solid var(--border);
      background: var(--panel-alt);
      overflow: auto;
    }

    .content {
      min-width: 0;
      padding: 18px;
      overflow: auto;
    }

    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      box-shadow: var(--shadow);
      padding: 16px;
      margin-bottom: 16px;
    }

    .card h2,
    .card h3 {
      margin-top: 0;
    }

    .toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }

    .field {
      display: grid;
      gap: 6px;
      margin-bottom: 12px;
    }

    .field label {
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }

    .grid-2 {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .grid-4 {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }

    .job-actions {
      margin: 12px 0 16px;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--panel);
    }

    .job-actions-title {
      margin-bottom: 7px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .job-counts {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 9px 0;
    }

    .job-action-message {
      min-height: 19px;
      margin-top: 9px;
      color: var(--muted);
      font-size: 12px;
      white-space: pre-wrap;
    }

    .item-list {
      margin-top: 14px;
      display: grid;
      gap: 8px;
    }

    .item-card {
      width: 100%;
      text-align: left;
      padding: 11px;
      border-radius: 9px;
      background: white;
    }

    .item-card.active {
      border-color: var(--primary);
      box-shadow:
        inset 3px 0 0 var(--primary);
    }

    .item-name {
      margin-bottom: 5px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .item-meta {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 3px 8px;
      background: #eee7dc;
      font-size: 12px;
      font-weight: 700;
    }

    .badge.review {
      background: #fff0bf;
      color: #765500;
    }

    .badge.approved_for_import {
      background: #dff3e7;
      color: #175533;
    }

    .badge.imported {
      background: #dcecf9;
      color: #165274;
    }

    .badge.failed,
    .badge.import_failed,
    .badge.rejected {
      background: #f8dddd;
      color: #7d2424;
    }

    .section-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }

    .section-title h3 {
      margin: 0;
    }

    .ingredient-row {
      display: grid;
      grid-template-columns:
        minmax(140px, 1.2fr)
        110px
        100px
        minmax(180px, 1.6fr)
        78px
        auto;
      gap: 8px;
      align-items: center;
      margin-bottom: 8px;
    }

    .instruction-row {
      display: grid;
      grid-template-columns:
        78px
        minmax(0, 1fr)
        auto;
      gap: 8px;
      align-items: start;
      margin-bottom: 10px;
    }

    .instruction-row textarea {
      min-height: 105px;
    }

    .warnings {
      display: grid;
      gap: 8px;
    }

    .warning {
      padding: 10px 12px;
      border-left: 4px solid #c88c16;
      background: #fff7df;
      border-radius: 6px;
      white-space: pre-wrap;
    }

    .empty {
      padding: 36px 16px;
      text-align: center;
      color: var(--muted);
    }

    .result {
      margin: 0;
      max-height: 480px;
      overflow: auto;
      background: #282521;
      color: #f4eee5;
      padding: 14px;
      border-radius: 9px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font:
        13px/1.5
        ui-monospace,
        SFMono-Regular,
        Consolas,
        monospace;
    }

    .review-box {
      padding: 12px;
      border: 1px dashed var(--border);
      border-radius: 10px;
      background: var(--panel-alt);
    }

    .status-line {
      color: var(--muted);
      font-size: 13px;
    }

    .llm-status-panel {
      margin: 12px 18px 0;
      padding: 12px 14px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--panel);
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }

    .llm-status-panel strong {
      margin-right: 4px;
    }

    .token-input {
      width: min(320px, 42vw);
    }

    .danger-zone {
      border-color: #e2b5b5;
    }

    .content > .card:first-child {
      position: sticky;
      top: 0;
      z-index: 30;
      box-shadow:
        0 10px 24px
        rgba(76, 58, 35, 0.14);
    }

    .sticky-feedback {
      margin-top: 7px;
      min-height: 20px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }

    .manual-note {
      padding: 10px 12px;
      border-left: 4px solid #47729e;
      background: #edf5fc;
      border-radius: 6px;
      white-space: pre-wrap;
    }

    .ingredient-row {
      grid-template-columns:
        minmax(130px, 1.2fr)
        120px
        90px
        90px
        90px
        120px
        minmax(170px, 1.5fr)
        72px
        auto;
    }

    .instruction-row {
      padding: 12px 0;
      border-bottom: 1px solid var(--border);
    }

    .instruction-timers {
      grid-column: 2 / -1;
      padding: 10px;
      border: 1px dashed var(--border);
      border-radius: 9px;
      background: var(--panel-alt);
    }

    .timer-toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 9px;
    }

    .timer-row {
      display: grid;
      grid-template-columns:
        minmax(150px, 1.5fr)
        105px
        85px
        85px
        90px
        80px
        auto;
      gap: 7px;
      align-items: center;
      margin-top: 7px;
    }

    .warning-blocking {
      border-left-color: var(--danger);
      background: #fdeaea;
    }

    .warning-confirmation {
      border-left-color: #c88c16;
      background: #fff7df;
    }

    .warning-info {
      border-left-color: #47729e;
      background: #edf5fc;
    }

    @media (max-width: 1000px) {
      .layout {
        grid-template-columns: 1fr;
      }

      .sidebar {
        border-right: 0;
        border-bottom: 1px solid var(--border);
        max-height: 420px;
      }

      .grid-4 {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .ingredient-row {
        grid-template-columns:
          repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 640px) {
      .topbar {
        align-items: flex-start;
        flex-direction: column;
      }

      .content {
        padding: 10px;
      }

      .grid-2,
      .grid-4 {
        grid-template-columns: 1fr;
      }

      .ingredient-row,
      .instruction-row {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>

<body>
<div class="app">
  <header class="topbar">
    <div>
      <h1>Food Assistant 审核中心</h1>
      <p>
        编辑、校验、批准并单道导入 Mealie
      </p>
    </div>

    <div class="toolbar">
      <span
        id="serviceStatus"
        class="status-line"
      >
        正在连接……
      </span>

      <input
        id="apiTokenInput"
        class="token-input"
        type="password"
        autocomplete="off"
        placeholder="Food Assistant API Token"
      >

      <button
        type="button"
        onclick="saveApiToken()"
      >
        保存令牌
      </button>

      <button
        type="button"
        onclick="forgetApiToken()"
      >
        清除令牌
      </button>

      <button
        type="button"
        onclick="refreshAll()"
      >
        刷新
      </button>
    </div>
  </header>

  <section class="llm-status-panel" aria-live="polite">
    <strong>AI 配置状态</strong>
    <span id="llmConfigStatus" class="status-line">
      认证后显示
    </span>
    <button
      id="llmTestButton"
      type="button"
      onclick="testLlmConnection()"
      disabled
    >
      测试连接
    </button>
  </section>

  <main class="layout">
    <aside class="sidebar">
      <div class="field">
        <label for="jobSelect">
          导入任务
        </label>

        <select
          id="jobSelect"
          onchange="changeJob()"
        >
          <option value="">
            正在加载……
          </option>
        </select>
      </div>

      <div
        id="jobActions"
        class="job-actions"
      >
        正在加载任务状态……
      </div>

      <div
        id="autoImportActions"
        class="job-actions"
      >
        <div class="status-line">
          无必须修正、无有效人工确认的菜谱：
        </div>

        <div
          class="toolbar"
          style="margin-top:8px"
        >
          <select
            id="autoImportCount"
            style="width:auto"
          >
            <option value="10">
              最多 10 道
            </option>

            <option
              value="20"
              selected
            >
              最多 20 道
            </option>

            <option value="50">
              最多 50 道
            </option>
          </select>

          <button
            id="autoImportPreviewButton"
            type="button"
            onclick="previewAutoImport()"
          >
            自动导入预览
          </button>

        </div>

        <div
          id="autoImportResult"
          class="job-action-message"
          style="margin-top:8px"
        >
          请先预览。
        </div>
      </div>

      <div class="field">
        <label for="statusFilter">
          状态筛选
        </label>

        <select
          id="statusFilter"
          onchange="renderItemList()"
        >
          <option value="">
            全部状态
          </option>
          <option value="review">
            待审核
          </option>
          <option value="approved_for_import">
            已批准
          </option>
          <option value="imported">
            已导入
          </option>
          <option value="failed">
            失败
          </option>
          <option value="rejected">
            已拒绝
          </option>
          <option value="cancelled">
            已跳过/已取消
          </option>
        </select>
      </div>

      <div class="field">
        <label>
          <input
            id="hideProcessed"
            type="checkbox"
            style="width:auto"
            checked
            onchange="toggleHideProcessed()"
          >
          隐藏已处理
        </label>
      </div>

      <div class="field">
        <label for="itemSearch">
          搜索菜谱
        </label>

        <input
          id="itemSearch"
          type="search"
          placeholder="输入菜名"
          oninput="renderItemList()"
        >
      </div>

      <div
        id="itemList"
        class="item-list"
      ></div>
    </aside>

    <section
      id="content"
      class="content"
    >
      <div class="card empty">
        从左侧选择一道菜谱。
      </div>
    </section>
  </main>
</div>

<script>
  const state = {
    jobs: [],
    items: [],
    currentJobId: null,
    currentItem: null,
    lastResult: null,
    lastResultIsError: false,
    apiToken:
      localStorage.getItem(
        "foodAssistantApiToken"
      ) || "",

    jobActionBusy: false,
    jobActionMessage: "",
    jobActionIsError: false,

    hideProcessed:
      localStorage.getItem(
        "foodAssistantHideProcessed"
      ) !== "false",

    autoImportBusy: false,
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatJson(value) {
    return JSON.stringify(
      value,
      null,
      2
    );
  }

  function normaliseCollection(value) {
    if (Array.isArray(value)) {
      return value;
    }

    if (!value || typeof value !== "object") {
      return [];
    }

    for (
      const key of [
        "items",
        "jobs",
        "results",
      ]
    ) {
      if (Array.isArray(value[key])) {
        return value[key];
      }
    }

    return [];
  }

  function extractError(data, response) {
    if (
      data
      && typeof data === "object"
      && "detail" in data
    ) {
      return typeof data.detail === "string"
        ? data.detail
        : formatJson(data.detail);
    }

    return (
      response.status
      + " "
      + response.statusText
    );
  }

  async function api(
    path,
    options = {}
  ) {
    const protectedApi =
      path.startsWith("/api/v1/");

    const response = await fetch(
      path,
      {
        headers: {
          "Accept": "application/json",
          ...(options.body
            ? {
                "Content-Type":
                  "application/json",
              }
            : {}),
          ...(protectedApi && state.apiToken
            ? {
                "Authorization":
                  `Bearer ${state.apiToken}`,
              }
            : {}),
          ...(options.headers || {}),
        },
        ...options,
      }
    );

    const raw = await response.text();

    let data = null;

    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = raw;
      }
    }

    if (!response.ok) {
      throw new Error(
        extractError(data, response)
      );
    }

    return data;
  }

  function setServiceStatus(
    text,
    isError = false
  ) {
    const element = document.getElementById(
      "serviceStatus"
    );

    element.textContent = text;
    element.style.color = isError
      ? "var(--danger)"
      : "var(--success)";
  }

  function setLlmConfigStatus(text, isError = false) {
    const element = document.getElementById(
      "llmConfigStatus"
    );
    element.textContent = text;
    element.style.color = isError
      ? "var(--danger)"
      : "var(--muted)";
  }

  async function loadLlmStatus() {
    const button = document.getElementById(
      "llmTestButton"
    );
    try {
      const data = await api(
        "/api/v1/system/llm-status"
      );
      setLlmConfigStatus(
        `Provider: ${data.provider}`
        + ` · Model: ${data.model}`
        + ` · API Key: ${
          data.api_key_configured ? "已配置" : "未配置"
        }`
      );
      button.disabled = !data.configured;
    } catch (error) {
      button.disabled = true;
      setLlmConfigStatus(error.message, true);
    }
  }

  async function testLlmConnection() {
    const button = document.getElementById(
      "llmTestButton"
    );
    button.disabled = true;
    setLlmConfigStatus("正在测试 AI 连接……");
    try {
      const data = await api(
        "/api/v1/system/llm-test",
        {method: "POST"}
      );
      setLlmConfigStatus(
        `${data.provider} · ${data.model}`
        + ` · 连接成功 (${data.latency_ms} ms)`
      );
    } catch (error) {
      setLlmConfigStatus(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  function saveApiToken() {
    const input = document.getElementById(
      "apiTokenInput"
    );

    const token = input.value.trim();

    if (token.length < 32) {
      setServiceStatus(
        "令牌无效或过短",
        true
      );
      return;
    }

    state.apiToken = token;

    localStorage.setItem(
      "foodAssistantApiToken",
      token
    );

    input.value = "";

    document.getElementById(
    "apiTokenInput"
  ).addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Enter") {
        saveApiToken();
      }
    }
  );

  refreshAll();
  }

  function forgetApiToken() {
    state.apiToken = "";

    localStorage.removeItem(
      "foodAssistantApiToken"
    );

    state.jobs = [];
    state.items = [];
    state.currentJobId = null;
    state.currentItem = null;

    document.getElementById(
      "jobSelect"
    ).innerHTML = `
      <option value="">
        需要 API Token
      </option>
    `;

    renderItemList();
    renderEmpty();

    setServiceStatus(
      "令牌已清除",
      true
    );
    document.getElementById(
      "llmTestButton"
    ).disabled = true;
    setLlmConfigStatus("认证后显示");
  }

  async function refreshAll() {
    const hideProcessedCheckbox =
      document.getElementById(
        "hideProcessed"
      );

    if (hideProcessedCheckbox) {
      hideProcessedCheckbox.checked =
        state.hideProcessed;
    }

    try {
      const health = await api(
        "/healthz"
      );

      if (!state.apiToken) {
        setServiceStatus(
          `服务正常 · v${
            health.version ?? "unknown"
          } · 请输入 API Token`,
          true
        );

        document.getElementById(
          "apiTokenInput"
        ).focus();

        return;
      }

      setServiceStatus(
        `服务正常 · v${
          health.version ?? "unknown"
        } · 已认证`
      );

      await loadLlmStatus();
      await loadJobs();

    } catch (error) {
      setServiceStatus(
        error.message,
        true
      );
    }
  }

  async function loadJobs() {
    const data = await api(
      "/api/v1/import-jobs"
    );

    state.jobs = normaliseCollection(
      data
    );

    const select = document.getElementById(
      "jobSelect"
    );

    const previous = String(
      state.currentJobId ?? ""
    );

    select.innerHTML = state.jobs
      .map((job) => {
        const id = job.id;
        const name =
          job.name
          ?? job.title
          ?? `任务 ${id}`;

        const status =
          job.status
          ?? "unknown";

        return `
          <option value="${escapeHtml(id)}">
            ${escapeHtml(name)}
            · ${escapeHtml(status)}
          </option>
        `;
      })
      .join("");

    if (!state.jobs.length) {
      select.innerHTML = `
        <option value="">
          没有导入任务
        </option>
      `;

      state.currentJobId = null;
      state.items = [];
      renderItemList();
      renderJobActions();
      return;
    }

    if (
      previous
      && state.jobs.some(
        (job) => String(job.id) === previous
      )
    ) {
      select.value = previous;
    }

    state.currentJobId = Number(
      select.value
    );

    await loadItems(
      state.currentJobId
    );
  }

  async function changeJob() {
    const value = document.getElementById(
      "jobSelect"
    ).value;

    state.currentJobId = value
      ? Number(value)
      : null;

    state.currentItem = null;
    state.lastResult = null;
    state.lastResultIsError = false;
    state.jobActionMessage = "";
    state.jobActionIsError = false;

    renderJobActions();

    if (state.currentJobId !== null) {
      await loadItems(
        state.currentJobId
      );
    }
  }

  async function loadItems(jobId) {
    const data = await api(
      `/api/v1/import-jobs/${jobId}/items?limit=1000`
    );

    state.items = normaliseCollection(
      data
    );

    const job = state.jobs.find(
      (value) =>
        Number(value.id)
        === Number(jobId)
    );

    if (job) {
      if (data.job_status) {
        job.status = data.job_status;
      }

      if (data.status_counts) {
        job.status_counts =
          data.status_counts;
      }

      if (data.total_items != null) {
        job.total_items =
          data.total_items;
      }
    }

    renderItemList();
    renderJobActions();

    if (state.currentItem) {
      const exists = state.items.some(
        (item) =>
          item.id === state.currentItem.id
      );

      if (exists) {
        await loadItem(
          state.currentItem.id
        );
      } else {
        state.currentItem = null;
        renderEmpty();
      }
    }
  }

  function currentJob() {
    return state.jobs.find(
      (job) =>
        Number(job.id)
        === Number(state.currentJobId)
    ) || null;
  }

  function renderJobActions() {
    const target = document.getElementById(
      "jobActions"
    );

    if (!target) {
      return;
    }

    const job = currentJob();

    if (!job) {
      target.innerHTML = `
        <div class="status-line">
          尚未选择任务。
        </div>
      `;
      return;
    }

    const counts =
      job.status_counts || {};

    const queued = Number(
      counts.queued || 0
    );

    const processing = Number(
      counts.processing || 0
    );

    const review = Number(
      counts.review || 0
    );

    const approved = Number(
      counts.approved_for_import || 0
    );

    const imported = Number(
      counts.imported || 0
    );

    const failed = Number(
      counts.failed || 0
    );

    const skipped = Number(
      counts.cancelled || 0
    );

    const canApprove = [
      "draft",
      "queued",
    ].includes(job.status);

    const canProcess = (
      [
        "approved",
        "processing",
      ].includes(job.status)
      && queued > 0
      && processing === 0
    );

    const messageColor =
      state.jobActionIsError
        ? "var(--danger)"
        : "var(--success)";

    target.innerHTML = `
      <div class="job-actions-title">
        ${escapeHtml(
          job.name
          ?? `任务 ${job.id}`
        )}
      </div>

      <div class="status-line">
        状态：
        <span class="badge ${
          escapeHtml(job.status)
        }">
          ${escapeHtml(job.status)}
        </span>
        · 共
        ${escapeHtml(
          job.total_items ?? 0
        )}
        道
      </div>

      <div class="job-counts">
        <span class="badge">
          queued ${queued}
        </span>

        <span class="badge review">
          review ${review}
        </span>

        <span class="badge approved_for_import">
          approved ${approved}
        </span>

        <span class="badge imported">
          imported ${imported}
        </span>

        ${
          processing
            ? `
              <span class="badge">
                processing ${processing}
              </span>
            `
            : ""
        }

        ${
          failed
            ? `
              <span class="badge failed">
                failed ${failed}
              </span>
            `
            : ""
        }

        ${
          skipped
            ? `
              <span class="badge">
                skipped ${skipped}
              </span>
            `
            : ""
        }
      </div>

      <div class="toolbar">
        <button
          id="approveJobButton"
          type="button"
          onclick="approveCurrentJob()"
          ${
            canApprove
            && !state.jobActionBusy
              ? ""
              : "disabled"
          }
        >
          批准当前任务
        </button>

        <button
          id="processNextButton"
          type="button"
          onclick="processNextRecipe()"
          ${
            canProcess
            && !state.jobActionBusy
              ? ""
              : "disabled"
          }
        >
          处理下一道
        </button>

        <select
          id="batchCountSelect"
          style="width:auto"
          ${
            canProcess
            && !state.jobActionBusy
              ? ""
              : "disabled"
          }
        >
          <option
            value="20"
            selected
          >
            20 道
          </option>

          <option value="50">
            50 道
          </option>
        </select>

        <button
          id="processBatchButton"
          type="button"
          class="primary"
          onclick="processAndAutoImportRecipes()"
          ${
            canProcess
            && !state.jobActionBusy
              ? ""
              : "disabled"
          }
        >
          ${
            state.jobActionBusy
              ? "正在处理并导入……"
              : "处理并自动导入"
          }
        </button>
      </div>

      <div
        class="job-action-message"
        style="color:${messageColor}"
      >
        ${escapeHtml(
          state.jobActionMessage
          || (
            canApprove
              ? "需要先批准任务。"
              : queued > 0
                ? "串行调用 Ollama；合格菜谱会直接写入 Mealie。"
                : "当前任务没有 queued 菜谱。"
          )
        )}
      </div>
    `;
  }

  function setAutoImportBusy(
    busy
  ) {
    state.autoImportBusy = busy;

    const previewButton =
      document.getElementById(
        "autoImportPreviewButton"
      );

    const runButton =
      document.getElementById(
        "autoImportRunButton"
      );

    if (previewButton) {
      previewButton.disabled = busy;
    }

    if (runButton) {
      runButton.disabled = busy;
      runButton.textContent = busy
        ? "正在执行……"
        : "执行自动导入";
    }
  }

  function setAutoImportResult(
    text,
    isError = false
  ) {
    const element =
      document.getElementById(
        "autoImportResult"
      );

    if (!element) {
      return;
    }

    element.textContent = text;
    element.style.color = isError
      ? "var(--danger)"
      : "var(--success)";
  }

  async function previewAutoImport() {
    const job = currentJob();

    if (!job || state.autoImportBusy) {
      return;
    }

    setAutoImportBusy(true);
    setAutoImportResult(
      "正在分析可自动导入的菜谱……"
    );

    try {
      const data = await api(
        `/api/v1/import-jobs/${
          job.id
        }/auto-import-preview?limit=1000`
      );

      const examples = (
        data.eligible || []
      )
        .slice(0, 5)
        .map(
          (item) => item.name
        )
        .join("、");

      setAutoImportResult(
        `可自动导入 ${
          data.eligible_count
        } 道；需要人工处理 ${
          data.requires_attention_count
        } 道。`
        + (
          examples
            ? ` 前几道：${examples}`
            : ""
        )
      );

      showResult(data);

    } catch (error) {
      setAutoImportResult(
        error.message,
        true
      );

      showResult(
        error.message,
        true
      );

    } finally {
      setAutoImportBusy(false);
    }
  }

  async function runAutoImport() {
    const job = currentJob();

    if (!job || state.autoImportBusy) {
      return;
    }

    const count = Number(
      document.getElementById(
        "autoImportCount"
      )?.value || 20
    );

    const confirmed = confirm(
      `确认自动导入最多 ${count} 道菜？\n\n`
      + `任务：${job.name}\n`
      + `规则：无必须修正、无有效人工确认\n`
      + `正常时间范围和水油语义提示会被忽略\n`
      + `连续失败 3 道将自动停止`
    );

    if (!confirmed) {
      return;
    }

    setAutoImportBusy(true);
    setAutoImportResult(
      "正在逐道批准并写入 Mealie……"
    );

    try {
      const data = await api(
        `/api/v1/import-jobs/${
          job.id
        }/auto-import`,
        {
          method: "POST",
          body: JSON.stringify({
            confirm_job_id:
              Number(job.id),
            max_items: count,
            stop_after_consecutive_failures:
              3,
          }),
        }
      );

      setAutoImportResult(
        `成功导入 ${
          data.imported_count
        } 道，失败 ${
          data.failed_count
        } 道，剩余可导入 ${
          data.remaining_eligible_count
        } 道。`
      );

      showResult(data);

      state.currentItem = null;
      await loadJobs();
      renderEmpty();

    } catch (error) {
      setAutoImportResult(
        error.message,
        true
      );

      showResult(
        error.message,
        true
      );

    } finally {
      setAutoImportBusy(false);
    }
  }

  async function approveCurrentJob() {
    const job = currentJob();

    if (!job || state.jobActionBusy) {
      return;
    }

    const total = Number(
      job.total_items || 0
    );

    const received = prompt(
      `确认批准任务“${
        job.name
      }”？\n\n`
      + `这只会开放逐道 AI 处理，`
      + `不会自动处理全部菜谱。\n\n`
      + `请输入菜谱总数 ${total} 进行确认：`
    );

    if (received === null) {
      return;
    }

    if (
      String(received).trim()
      !== String(total)
    ) {
      state.jobActionMessage =
        `确认数字不匹配，要求输入 ${total}。`;

      state.jobActionIsError = true;
      renderJobActions();
      return;
    }

    state.jobActionBusy = true;
    state.jobActionMessage =
      "正在批准当前任务……";
    state.jobActionIsError = false;

    renderJobActions();

    try {
      const data = await api(
        `/api/v1/import-jobs/${
          job.id
        }/approve`,
        {
          method: "POST",
          body: JSON.stringify({
            confirm_total: total,
          }),
        }
      );

      state.jobActionMessage =
        data.message
        || "任务已经批准。";

      state.jobActionIsError = false;

      await loadJobs();

    } catch (error) {
      state.jobActionMessage =
        error.message;

      state.jobActionIsError = true;

    } finally {
      state.jobActionBusy = false;
      renderJobActions();
    }
  }

  async function processAndAutoImportRecipes() {
    const job = currentJob();

    if (!job || state.jobActionBusy) {
      return;
    }

    const select = document.getElementById(
      "batchCountSelect"
    );

    const count = Number(
      select?.value || 20
    );

    const queued = Number(
      job.status_counts?.queued || 0
    );

    if (queued <= 0) {
      state.jobActionMessage =
        "当前任务没有 queued 菜谱。";

      state.jobActionIsError = true;
      renderJobActions();
      return;
    }

    const actualMaximum = Math.min(
      count,
      queued
    );

    const confirmed = confirm(
      `确认处理并自动导入最多 ${
        actualMaximum
      } 道菜？\n\n`
      + `任务：${job.name}\n`
      + `处理：逐道串行调用 Ollama\n`
      + `合格：自动批准并写入 Mealie\n`
      + `需确认：保留 review\n`
      + `单道失败：继续下一道\n`
      + `Ollama 断线或显存不足：立即停止\n`
      + `整批结束后自动卸载模型`
    );

    if (!confirmed) {
      return;
    }

    state.jobActionBusy = true;
    state.jobActionMessage =
      "正在处理并自动导入……";

    state.jobActionIsError = false;
    renderJobActions();

    try {
      const data = await api(
        `/api/v1/import-jobs/${
          job.id
        }/process-and-auto-import`,
        {
          method: "POST",
          body: JSON.stringify({
            count: actualMaximum,
            unload_model_after_batch: true,
          }),
        }
      );

      const totalFailed = (
        Number(
          data.processing_failed_count || 0
        )
        + Number(
          data.import_failed_count || 0
        )
      );

      state.jobActionMessage = (
        `已标准化 ${
          data.normalized_count
        } 道；`
        + `导入 ${
          data.imported_count
        } 道；`
        + `待人工确认 ${
          data.requires_review_count
        } 道；`
        + `失败 ${totalFailed} 道。`
      );

      state.jobActionIsError = Boolean(
        data.infrastructure_error
      );

      showResult(data);

      state.currentItem = null;

      await loadJobs();

      const filter =
        document.getElementById(
          "statusFilter"
        );

      if (
        Number(
          data.processing_failed_count || 0
        ) > 0
      ) {
        filter.value = "failed";

      } else if (
        Number(
          data.requires_review_count || 0
        ) > 0
      ) {
        filter.value = "review";

      } else {
        filter.value = "";
      }

      renderItemList();
      renderEmpty();

      if (data.infrastructure_error) {
        alert(
          "Ollama 出现基础设施错误，批处理已停止。"
          + "\n相关项目已重新放回 queued，"
          + "不会留作菜谱处理失败。"
        );
      }

    } catch (error) {
      state.jobActionMessage =
        error.message;

      state.jobActionIsError = true;

      showResult(
        error.message,
        true
      );

    } finally {
      state.jobActionBusy = false;
      renderJobActions();
    }
  }


  async function processBatchRecipes() {
    const job = currentJob();

    if (!job || state.jobActionBusy) {
      return;
    }

    const select = document.getElementById(
      "batchCountSelect"
    );

    const count = Number(
      select?.value || 3
    );

    const queued = Number(
      job.status_counts?.queued || 0
    );

    const actualMaximum = Math.min(
      count,
      queued
    );

    if (actualMaximum <= 0) {
      state.jobActionMessage =
        "当前任务没有 queued 菜谱。";

      state.jobActionIsError = true;
      renderJobActions();
      return;
    }

    const confirmed = confirm(
      `确认连续标准化最多 ${
        actualMaximum
      } 道菜？\n\n`
      + `任务：${job.name}\n`
      + `处理方式：逐道串行调用 Ollama\n`
      + `完成状态：只到 review\n\n`
      + `不会自动批准，也不会写入 Mealie。`
    );

    if (!confirmed) {
      return;
    }

    state.jobActionBusy = true;
    state.jobActionMessage =
      `正在串行处理最多 ${
        actualMaximum
      } 道菜。`
      + "任意一道失败都会立即停止。";

    state.jobActionIsError = false;
    renderJobActions();

    let result = null;
    let requestError = null;

    try {
      result = await api(
        `/api/v1/import-jobs/${
          job.id
        }/process-batch`,
        {
          method: "POST",
          body: JSON.stringify({
            count: actualMaximum,
          }),
        }
      );

    } catch (error) {
      requestError = error;
    }

    try {
      await loadJobs();

      state.currentJobId =
        Number(job.id);

      const jobSelect =
        document.getElementById(
          "jobSelect"
        );

      if (jobSelect) {
        jobSelect.value =
          String(job.id);
      }

      await loadItems(
        Number(job.id)
      );

      const processedIds = (
        result?.processed_items || []
      )
        .map(
          (item) => Number(item.item_id)
        )
        .filter(Number.isFinite);

      const firstProcessedReview =
        state.items.find(
          (item) =>
            processedIds.includes(
              Number(item.id)
            )
            && item.status === "review"
        );

      const firstReview =
        firstProcessedReview
        || state.items.find(
          (item) =>
            item.status === "review"
        );

      if (firstReview) {
        await loadItem(
          Number(firstReview.id)
        );
      }

    } catch (refreshError) {
      if (!requestError) {
        requestError = refreshError;
      }
    }

    if (requestError) {
      state.jobActionMessage =
        requestError.message;

      state.jobActionIsError = true;

      showResult(
        requestError.message,
        true
      );

    } else {
      const processedCount = Number(
        result?.processed_count || 0
      );

      if (result?.stop_reason === "item_failed") {
        state.jobActionMessage =
          `本批成功处理 ${
            processedCount
          } 道，随后因一道失败而停止。`;

        state.jobActionIsError = true;

      } else {
        state.jobActionMessage =
          `本批已处理 ${
            processedCount
          } 道，均只进入人工审核。`;

        state.jobActionIsError = false;
      }

      showResult(result);
    }

    state.jobActionBusy = false;
    renderJobActions();
  }


  async function processNextRecipe() {
    const job = currentJob();

    if (!job || state.jobActionBusy) {
      return;
    }

    const targetItem = state.items
      .filter(
        (item) =>
          item.status === "queued"
      )
      .sort(
        (left, right) =>
          Number(left.id)
          - Number(right.id)
      )[0];

    if (!targetItem) {
      state.jobActionMessage =
        "当前任务没有 queued 菜谱。";

      state.jobActionIsError = true;
      renderJobActions();
      return;
    }

    const name = itemName(targetItem);

    const confirmed = confirm(
      `确认调用 Ollama 处理下一道菜？\n\n`
      + `任务：${job.name}\n`
      + `菜谱：${name}\n`
      + `Item：#${targetItem.id}\n\n`
      + `本次只处理这一道。`
    );

    if (!confirmed) {
      return;
    }

    state.jobActionBusy = true;
    state.jobActionMessage =
      `正在调用 Ollama 处理“${name}”，`
      + "通常需要几十秒到数分钟，请勿重复点击。";

    state.jobActionIsError = false;
    renderJobActions();

    let result = null;
    let processError = null;

    try {
      result = await api(
        `/api/v1/import-jobs/${
          job.id
        }/process-next`,
        {
          method: "POST",
        }
      );

    } catch (error) {
      processError = error;
    }

    state.currentItem = null;

    try {
      await loadJobs();

      state.currentJobId =
        Number(job.id);

      const jobSelect =
        document.getElementById(
          "jobSelect"
        );

      if (jobSelect) {
        jobSelect.value =
          String(job.id);
      }

      await loadItems(
        Number(job.id)
      );

      const updatedItem = state.items.find(
        (item) =>
          Number(item.id)
          === Number(targetItem.id)
      );

      if (
        updatedItem
        && updatedItem.status !== "queued"
      ) {
        await loadItem(
          Number(targetItem.id)
        );
      } else {
        throw new Error(
          "处理请求已结束，但暂时无法读取"
          + "刚处理的菜谱状态。请点击刷新。"
        );
      }

    } catch (refreshError) {
      if (!processError) {
        processError = refreshError;
      }
    }

    if (processError) {
      state.jobActionMessage =
        processError.message;

      state.jobActionIsError = true;

      showResult(
        processError.message,
        true
      );

    } else {
      state.jobActionMessage =
        `“${name}”处理完成，`
        + "已自动打开审核结果。";

      state.jobActionIsError = false;

      showResult(
        result
        || {
          message:
            "菜谱处理完成。",
        }
      );
    }

    state.jobActionBusy = false;
    renderJobActions();
  }

  function isIgnorableTimerWarning(
    warning
  ) {
    const value = String(
      warning ?? ""
    );

    if (
      !value.startsWith("[需要确认]")
      && !value.startsWith("[系统校验]")
    ) {
      return false;
    }

    return [
      "包含时间范围",
      "范围计时器建议",
      "接受范围计时器",
      "没有自动生成单一计时器",
    ].some(
      (phrase) => value.includes(phrase)
    );
  }

  function isHiddenSemanticNotice(
    warning
  ) {
    const value = String(
      warning ?? ""
    );

    if (
      !value.startsWith("[信息提示]")
      && !value.startsWith("[系统补全]")
    ) {
      return false;
    }

    const mentionsProcessIngredient = (
      value.includes("食用油")
      || value.includes("“水”")
      || value.includes("水作为")
    );

    const isSemanticNotice = [
      "根据步骤补入",
      "作为语义用量补入",
      "不要求虚构固定数量",
      "不参与库存扣减",
    ].some(
      (phrase) => value.includes(phrase)
    );

    return (
      mentionsProcessIngredient
      && isSemanticNotice
    );
  }

  function toggleHideProcessed() {
    const checkbox =
      document.getElementById(
        "hideProcessed"
      );

    state.hideProcessed = Boolean(
      checkbox?.checked
    );

    localStorage.setItem(
      "foodAssistantHideProcessed",
      String(state.hideProcessed)
    );

    renderItemList();
  }

  function itemName(item) {
    return (
      item.source_title
      ?? item.title
      ?? item.name
      ?? item.normalized?.name
      ?? `菜谱 ${item.id}`
    );
  }

  function renderItemList() {
    const target = document.getElementById(
      "itemList"
    );

    const status = document.getElementById(
      "statusFilter"
    ).value;

    const search = document.getElementById(
      "itemSearch"
    ).value
      .trim()
      .toLocaleLowerCase();

    const hiddenStatuses = new Set([
      "imported",
      "rejected",
      "cancelled",
      "skipped_duplicate",
      "completed",
    ]);

    const hideProcessed = (
      state.hideProcessed
      && !status
    );

    const items = state.items.filter(
      (item) => {
        if (
          hideProcessed
          && hiddenStatuses.has(
            item.status
          )
        ) {
          return false;
        }

        if (
          status
          && item.status !== status
        ) {
          return false;
        }

        if (
          search
          && !itemName(item)
            .toLocaleLowerCase()
            .includes(search)
        ) {
          return false;
        }

        return true;
      }
    );

    if (!items.length) {
      target.innerHTML = `
        <div class="empty">
          没有匹配的菜谱。
        </div>
      `;
      return;
    }

    target.innerHTML = items
      .map((item) => {
        const active =
          state.currentItem
          && state.currentItem.id === item.id;

        return `
          <button
            type="button"
            class="item-card ${
              active ? "active" : ""
            }"
            onclick="loadItem(${Number(item.id)})"
          >
            <div class="item-name">
              ${escapeHtml(itemName(item))}
            </div>

            <div class="item-meta">
              <span>#${escapeHtml(item.id)}</span>

              <span class="badge ${
                escapeHtml(item.status)
              }">
                ${escapeHtml(item.status)}
              </span>
            </div>
          </button>
        `;
      })
      .join("");
  }

  async function loadItem(itemId) {
    const changingItem = (
      !state.currentItem
      || state.currentItem.id !== itemId
    );

    if (changingItem) {
      state.lastResult = null;
      state.lastResultIsError = false;
    }

    try {
      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${itemId}`
      );

      state.currentItem =
        data.item ?? data;

      renderItemList();
      renderEditor();

    } catch (error) {
      showResult(
        error.message,
        true
      );
    }
  }

  function renderEmpty() {
    document.getElementById(
      "content"
    ).innerHTML = `
      <div class="card empty">
        从左侧选择一道菜谱。
      </div>
    `;
  }

  function splitList(value) {
    return String(value ?? "")
      .split(/[,，\n]/)
      .map((part) => part.trim())
      .filter(Boolean);
  }

  function numericOrNull(value) {
    const text = String(value).trim();

    if (!text) {
      return null;
    }

    const number = Number(text);

    if (!Number.isFinite(number)) {
      throw new Error(
        `无效数字：${text}`
      );
    }

    return number;
  }

  function selectedOption(
    value,
    current
  ) {
    return value === current
      ? "selected"
      : "";
  }

  function timerUiParts(timer = {}) {
    let seconds =
      timer.kind === "range"
        ? timer.duration_min_seconds
        : timer.duration_seconds;

    seconds = Number(seconds || 0);

    let unit = "秒";
    let divisor = 1;

    if (
      seconds > 0
      && seconds % 3600 === 0
    ) {
      unit = "小时";
      divisor = 3600;

    } else if (
      seconds > 0
      && seconds % 60 === 0
    ) {
      unit = "分钟";
      divisor = 60;
    }

    const minimum = seconds
      ? seconds / divisor
      : "";

    const maximumSeconds = Number(
      timer.duration_max_seconds || 0
    );

    const maximum = maximumSeconds
      ? maximumSeconds / divisor
      : "";

    return {
      minimum,
      maximum,
      unit,
    };
  }

  function timerRow(
    timer = {}
  ) {
    const kind =
      timer.kind ?? "fixed";

    const source =
      timer.source ?? "manual";

    const parts = timerUiParts(timer);

    return `
      <div
        class="timer-row"
        data-source="${escapeHtml(source)}"
      >
        <input
          class="timer-name"
          value="${escapeHtml(
            timer.name ?? ""
          )}"
          placeholder="计时器名称"
        >

        <select
          class="timer-kind"
          onchange="syncTimerRow(this)"
        >
          <option
            value="fixed"
            ${selectedOption(
              "fixed",
              kind
            )}
          >
            固定时间
          </option>

          <option
            value="range"
            ${selectedOption(
              "range",
              kind
            )}
          >
            时间范围
          </option>
        </select>

        <input
          class="timer-minimum"
          type="number"
          min="0.01"
          step="any"
          value="${escapeHtml(
            parts.minimum
          )}"
          placeholder="时长/最短"
        >

        <input
          class="timer-maximum"
          type="number"
          min="0.01"
          step="any"
          value="${escapeHtml(
            parts.maximum
          )}"
          placeholder="最长"
          ${
            kind === "range"
              ? ""
              : "disabled"
          }
        >

        <select class="timer-unit">
          ${["秒", "分钟", "小时"]
            .map(
              (unit) => `
                <option
                  value="${unit}"
                  ${selectedOption(
                    unit,
                    parts.unit
                  )}
                >
                  ${unit}
                </option>
              `
            )
            .join("")}
        </select>

        <label>
          <input
            class="timer-accepted"
            type="checkbox"
            style="width:auto"
            ${
              timer.accepted !== false
                ? "checked"
                : ""
            }
          >
          接受
        </label>

        <button
          type="button"
          class="danger"
          onclick="this.parentElement.remove()"
        >
          删除
        </button>
      </div>
    `;
  }

  function syncTimerRow(select) {
    const row = select.closest(
      ".timer-row"
    );

    const isRange =
      select.value === "range";

    const maximum = row.querySelector(
      ".timer-maximum"
    );

    maximum.disabled = !isRange;

    if (!isRange) {
      maximum.value = "";
    }
  }

  function addTimer(button) {
    const instruction = button.closest(
      ".instruction-row"
    );

    instruction.querySelector(
      ".timer-list"
    ).insertAdjacentHTML(
      "beforeend",
      timerRow({
        kind: "fixed",
        source: "manual",
        accepted: true,
      })
    );
  }

  function durationMultiplier(unit) {
    if (unit === "小时") {
      return 3600;
    }

    if (unit === "分钟") {
      return 60;
    }

    return 1;
  }

  function detectTimersInRow(button) {
    const row = button.closest(
      ".instruction-row"
    );

    const textValue = row.querySelector(
      ".instruction-text"
    ).value;

    const stepNumber =
      row.querySelector(
        ".instruction-number"
      ).value || "?";

    const target = row.querySelector(
      ".timer-list"
    );

    target.querySelectorAll(
      '.timer-row[data-source="automatic"]'
    ).forEach(
      (element) => element.remove()
    );

    const rangePattern =
      /(\d+(?:\.\d+)?)\s*(?:-|–|—|~|～|至|到)\s*(\d+(?:\.\d+)?)\s*(秒钟?|分钟|小时)/g;

    const exactPattern =
      /(\d+(?:\.\d+)?)\s*(秒钟?|分钟|小时)/g;

    const rangeSpans = [];

    for (
      const match of textValue.matchAll(
        rangePattern
      )
    ) {
      const start = match.index;
      const end =
        start + match[0].length;

      rangeSpans.push([start, end]);

      const unit = match[3].startsWith("秒")
        ? "秒"
        : match[3];

      const multiplier =
        durationMultiplier(unit);

      target.insertAdjacentHTML(
        "beforeend",
        timerRow({
          name:
            `步骤 ${stepNumber} 检查时间`,
          kind: "range",
          duration_min_seconds:
            Number(match[1])
            * multiplier,
          duration_max_seconds:
            Number(match[2])
            * multiplier,
          source: "automatic",
          accepted: false,
        })
      );
    }

    for (
      const match of textValue.matchAll(
        exactPattern
      )
    ) {
      const start = match.index;
      const end =
        start + match[0].length;

      const overlaps = rangeSpans.some(
        ([rangeStart, rangeEnd]) =>
          start < rangeEnd
          && rangeStart < end
      );

      if (overlaps) {
        continue;
      }

      const unit = match[2].startsWith("秒")
        ? "秒"
        : match[2];

      const multiplier =
        durationMultiplier(unit);

      target.insertAdjacentHTML(
        "beforeend",
        timerRow({
          name:
            `步骤 ${stepNumber} 计时 ${match[0]}`,
          kind: "fixed",
          duration_seconds:
            Number(match[1])
            * multiplier,
          source: "automatic",
          accepted: true,
        })
      );
    }
  }

  function detectAllTimers() {
    document.querySelectorAll(
      ".instruction-row"
    ).forEach((row) => {
      const button = row.querySelector(
        ".detect-timers"
      );

      detectTimersInRow(button);
    });

    setActionFeedback(
      "计时器建议已经生成；范围计时器需要人工接受。"
    );
  }

  function syncIngredientAmount(select) {
    const row = select.closest(
      ".ingredient-row"
    );

    const mode = select.value;

    const quantity = row.querySelector(
      ".ingredient-quantity"
    );

    const maximum = row.querySelector(
      ".ingredient-quantity-max"
    );

    const unit = row.querySelector(
      ".ingredient-unit"
    );

    const numeric = [
      "exact",
      "range",
    ].includes(mode);

    quantity.disabled = !numeric;
    maximum.disabled = mode !== "range";
    unit.disabled = !numeric;

    if (!numeric) {
      quantity.value = "";
      maximum.value = "";
      unit.value = "";
    }

    if (mode !== "range") {
      maximum.value = "";
    }
  }

  function ingredientRow(
    ingredient = {},
    originalIndex = -1
  ) {
    const amountMode =
      ingredient.amount_mode
      ?? (
        ingredient.quantity != null
          ? "exact"
          : "unspecified"
      );

    const role =
      ingredient.role ?? "main";

    const numeric = [
      "exact",
      "range",
    ].includes(amountMode);

    return `
      <div
        class="ingredient-row"
        data-original-index="${originalIndex}"
      >
        <input
          class="ingredient-food"
          value="${escapeHtml(
            ingredient.food_name ?? ""
          )}"
          placeholder="食材名称"
        >

        <select
          class="ingredient-amount-mode"
          onchange="syncIngredientAmount(this)"
        >
          <option value="exact"
            ${selectedOption(
              "exact",
              amountMode
            )}>
            精确
          </option>

          <option value="range"
            ${selectedOption(
              "range",
              amountMode
            )}>
            范围
          </option>

          <option value="as_needed"
            ${selectedOption(
              "as_needed",
              amountMode
            )}>
            适量
          </option>

          <option value="coverage"
            ${selectedOption(
              "coverage",
              amountMode
            )}>
            覆盖条件
          </option>

          <option value="to_taste"
            ${selectedOption(
              "to_taste",
              amountMode
            )}>
            按口味
          </option>

          <option value="unspecified"
            ${selectedOption(
              "unspecified",
              amountMode
            )}>
            未注明
          </option>
        </select>

        <input
          class="ingredient-quantity"
          type="number"
          step="any"
          value="${escapeHtml(
            ingredient.quantity ?? ""
          )}"
          placeholder="数量/最小"
          ${numeric ? "" : "disabled"}
        >

        <input
          class="ingredient-quantity-max"
          type="number"
          step="any"
          value="${escapeHtml(
            ingredient.quantity_max ?? ""
          )}"
          placeholder="最大"
          ${
            amountMode === "range"
              ? ""
              : "disabled"
          }
        >

        <input
          class="ingredient-unit"
          value="${escapeHtml(
            ingredient.unit ?? ""
          )}"
          placeholder="单位"
          ${numeric ? "" : "disabled"}
        >

        <select class="ingredient-role">
          <option value="main"
            ${selectedOption(
              "main",
              role
            )}>
            主体食材
          </option>

          <option value="seasoning"
            ${selectedOption(
              "seasoning",
              role
            )}>
            调味料
          </option>

          <option value="process"
            ${selectedOption(
              "process",
              role
            )}>
            工艺耗材
          </option>

          <option value="garnish"
            ${selectedOption(
              "garnish",
              role
            )}>
            装饰配料
          </option>
        </select>

        <input
          class="ingredient-note"
          value="${escapeHtml(
            ingredient.note ?? ""
          )}"
          placeholder="备注或使用条件"
        >

        <label>
          <input
            class="ingredient-optional"
            type="checkbox"
            style="width:auto"
            ${
              ingredient.optional
                ? "checked"
                : ""
            }
          >
          可选
        </label>

        <button
          type="button"
          class="danger"
          onclick="this.parentElement.remove()"
        >
          删除
        </button>
      </div>
    `;
  }

  function instructionRow(
    instruction = {},
    originalIndex = -1
  ) {
    return `
      <div
        class="instruction-row"
        data-original-index="${originalIndex}"
      >
        <input
          class="instruction-number"
          type="number"
          min="1"
          value="${escapeHtml(
            instruction.step_number ?? ""
          )}"
          placeholder="序号"
        >

        <textarea
          class="instruction-text"
          placeholder="操作步骤"
        >${escapeHtml(
          instruction.text ?? ""
        )}</textarea>

        <button
          type="button"
          class="danger"
          onclick="this.parentElement.remove()"
        >
          删除步骤
        </button>

        <div class="instruction-timers">
          <div class="timer-toolbar">
            <button
              type="button"
              class="detect-timers"
              onclick="detectTimersInRow(this)"
            >
              从文字识别计时器
            </button>

            <button
              type="button"
              onclick="addTimer(this)"
            >
              手动添加计时器
            </button>
          </div>

          <div class="timer-list">
            ${(instruction.timers ?? [])
              .map(
                (timer) =>
                  timerRow(timer)
              )
              .join("")}
          </div>
        </div>
      </div>
    `;
  }

  function renderEditor() {
    const item = state.currentItem;
    const recipe = item.normalized;

    if (!recipe) {
      const canRetry = [
        "failed",
        "source_updated",
        "processing",
      ].includes(item.status);
      const canProcess =
        item.status === "queued";

      document.getElementById(
        "content"
      ).innerHTML = `
        <div class="card">
          <h2>
            ${escapeHtml(
              item.source_title
              ?? `Item #${item.id}`
            )}
          </h2>

          <div class="status-line">
            Item #${escapeHtml(item.id)}
            ·
            <span class="badge ${
              escapeHtml(item.status)
            }">
              ${escapeHtml(item.status)}
            </span>
          </div>

          <p>
            此项目没有可用的标准化结果。
          </p>

          ${
            item.error
              ? `
                <pre class="result">${
                  escapeHtml(item.error)
                }</pre>
              `
              : ""
          }

          <div
            id="retryItemMessage"
            class="sticky-feedback"
            style="margin-top:14px"
          ></div>

          <div
            class="toolbar"
            style="margin-top:14px"
          >
            ${
              canProcess
                ? `
                  <button
                    id="processItemButton"
                    type="button"
                    class="primary"
                    onclick="processCurrentQueuedItem()"
                  >
                    处理此菜谱
                  </button>
                `
                : `
                  <button
                    id="retryItemButton"
                    type="button"
                    class="primary"
                    onclick="retryCurrentItem()"
                    ${canRetry ? "" : "disabled"}
                  >
                    重试 AI 标准化
                  </button>
                `
            }
          </div>

          <p class="status-line">
            ${
              canProcess
                ? "只处理当前选中项目，不会自动导入 Mealie。"
                : "重试只会把本项目放回 queued；之后可在详情页处理。"
            }
          </p>
        </div>
      `;
      return;
    }

    const warnings = Array.isArray(
      recipe.warnings
    )
      ? recipe.warnings
      : [];

    const manualReviewNotes = warnings.filter(
      (warning) =>
        String(warning).startsWith(
          "[人工审核]"
        )
    );

    const blockingWarnings = warnings.filter(
      (warning) =>
        String(warning).startsWith(
          "[必须修正]"
        )
    );

    const confirmationWarnings = warnings.filter(
      (warning) =>
        (
          String(warning).startsWith(
            "[需要确认]"
          )
          || String(warning).startsWith(
            "[系统校验]"
          )
        )
        && !isIgnorableTimerWarning(
          warning
        )
    );

    const infoWarnings = warnings.filter(
      (warning) =>
        (
          String(warning).startsWith(
            "[信息提示]"
          )
          || String(warning).startsWith(
            "[系统补全]"
          )
        )
        && !isHiddenSemanticNotice(
          warning
        )
    );

    const systemWarnings = [
      ...blockingWarnings,
      ...confirmationWarnings,
    ];

    const status = item.status;

    const canSave = [
      "review",
      "approved_for_import",
    ].includes(status);

    const canApprove = (
      status === "review"
      && blockingWarnings.length === 0
    );

    const canImport =
      status === "approved_for_import";

    const canReject = [
      "review",
      "approved_for_import",
      "failed",
    ].includes(status);

    const canRestoreRejected =
      status === "rejected";

    document.getElementById(
      "content"
    ).innerHTML = `
      <div class="card">
        <div class="section-title">
          <div>
            <h2>
              ${escapeHtml(recipe.name)}
            </h2>

            <div class="status-line">
              Item #${escapeHtml(item.id)}
              ·
              <span class="badge ${
                escapeHtml(status)
              }">
                ${escapeHtml(status)}
              </span>
            </div>

            <div
              id="actionFeedback"
              class="sticky-feedback"
            >
              等待操作。
            </div>
          </div>

          <div class="toolbar">
            <button
              type="button"
              onclick="nativePreview()"
            >
              原生结构预览
            </button>

            <button
              type="button"
              onclick="saveItem()"
              ${canSave ? "" : "disabled"}
            >
              仅保存
            </button>

            <button
              type="button"
              class="primary"
              onclick="saveAndRevalidateItem()"
              ${canSave ? "" : "disabled"}
            >
              保存并校验
            </button>

            <button
              type="button"
              class="success"
              onclick="approveItem()"
              ${canApprove ? "" : "disabled"}
            >
              批准导入
            </button>

            <button
              type="button"
              class="primary"
              onclick="importItem()"
              ${canImport ? "" : "disabled"}
            >
              导入 Mealie
            </button>

            <button
              type="button"
              onclick="restoreRejectedItem()"
              ${canRestoreRejected ? "" : "disabled"}
            >
              撤销拒绝并恢复审核
            </button>
          </div>
        </div>
      </div>

      <div class="card">
        <h3>基本信息</h3>

        <div class="grid-2">
          <div class="field">
            <label>菜谱名称</label>
            <input
              id="recipeName"
              value="${escapeHtml(recipe.name)}"
            >
          </div>

          <div class="field">
            <label>菜系</label>
            <input
              id="recipeCuisine"
              value="${escapeHtml(
                recipe.cuisine ?? ""
              )}"
            >
          </div>
        </div>

        <div class="field">
          <label>描述</label>
          <textarea id="recipeDescription">${
            escapeHtml(
              recipe.description ?? ""
            )
          }</textarea>
        </div>

        <div class="grid-2">
          <div class="field">
            <label>
              分类，用逗号分隔
            </label>
            <input
              id="recipeCategories"
              value="${escapeHtml(
                (recipe.categories ?? [])
                  .join(", ")
              )}"
            >
          </div>

          <div class="field">
            <label>
              标签，用逗号分隔
            </label>
            <input
              id="recipeTags"
              value="${escapeHtml(
                (recipe.tags ?? [])
                  .join(", ")
              )}"
            >
          </div>
        </div>

        <div class="grid-4">
          <div class="field">
            <label>份数</label>
            <input
              id="recipeServings"
              type="number"
              step="any"
              value="${escapeHtml(
                recipe.servings ?? ""
              )}"
            >
          </div>

          <div class="field">
            <label>准备时间/分钟</label>
            <input
              id="recipePrepTime"
              type="number"
              step="any"
              value="${escapeHtml(
                recipe.prep_time_minutes
                ?? ""
              )}"
            >
          </div>

          <div class="field">
            <label>烹饪时间/分钟</label>
            <input
              id="recipeCookTime"
              type="number"
              step="any"
              value="${escapeHtml(
                recipe.cook_time_minutes
                ?? ""
              )}"
            >
          </div>

          <div class="field">
            <label>总时间/分钟</label>
            <input
              id="recipeTotalTime"
              type="number"
              step="any"
              value="${escapeHtml(
                recipe.total_time_minutes
                ?? ""
              )}"
            >
          </div>
        </div>
      </div>

      <div class="card">
        <div class="section-title">
          <h3>食材</h3>

          <button
            type="button"
            onclick="addIngredient()"
          >
            添加食材
          </button>
        </div>

        <div id="ingredients">
          ${(recipe.ingredients ?? [])
            .map(
              (ingredient, index) =>
                ingredientRow(
                  ingredient,
                  index
                )
            )
            .join("")}
        </div>
      </div>

      <div class="card">
        <div class="section-title">
          <h3>步骤与计时器</h3>

          <div class="toolbar">
            <button
              type="button"
              onclick="detectAllTimers()"
            >
              生成全部计时器建议
            </button>

            <button
              type="button"
              onclick="addInstruction()"
            >
              添加步骤
            </button>
          </div>
        </div>

        <div id="instructions">
          ${(recipe.instructions ?? [])
            .map(
              (instruction, index) =>
                instructionRow(
                  instruction,
                  index
                )
            )
            .join("")}
        </div>
      </div>

      <div class="card">
        <h3>
          必须修正
          (${blockingWarnings.length})
        </h3>

        <div class="warnings">
          ${
            blockingWarnings.length
              ? blockingWarnings
                  .map(
                    (warning) => `
                      <div class="warning warning-blocking">
                        ${escapeHtml(warning)}
                      </div>
                    `
                  )
                  .join("")
              : `
                <div class="status-line">
                  没有阻止批准的问题。
                </div>
              `
          }
        </div>
      </div>

      <div class="card">
        <h3>
          需要人工确认
          (${confirmationWarnings.length})
        </h3>

        <div class="warnings">
          ${
            confirmationWarnings.length
              ? confirmationWarnings
                  .map(
                    (warning) => `
                      <div class="warning warning-confirmation">
                        ${escapeHtml(warning)}
                      </div>
                    `
                  )
                  .join("")
              : `
                <div class="status-line">
                  当前不需要额外人工确认。
                </div>
              `
          }
        </div>
      </div>

      <div class="card">
        <h3>
          信息提示
          (${infoWarnings.length})
        </h3>

        <div class="warnings">
          ${
            infoWarnings.length
              ? infoWarnings
                  .map(
                    (warning) => `
                      <div class="warning warning-info">
                        ${escapeHtml(warning)}
                      </div>
                    `
                  )
                  .join("")
              : `
                <div class="status-line">
                  当前没有信息提示。
                </div>
              `
          }
        </div>
      </div>

      <div class="card">
        <h3>人工审核记录</h3>

        <div class="warnings">
          ${
            manualReviewNotes.length
              ? manualReviewNotes
                  .map(
                    (note) => `
                      <div class="manual-note">
                        ${escapeHtml(
                          String(note).replace(
                            /^\[人工审核\]\s*/,
                            ""
                          )
                        )}
                      </div>
                    `
                  )
                  .join("")
              : `
                <div class="status-line">
                  当前没有人工审核记录。
                </div>
              `
          }
        </div>
      </div>

      <div class="card">
        <h3>人工审核</h3>

        <div class="review-box">
          <div class="field">
            <label>
              审核说明
            </label>

            <textarea
              id="reviewNote"
              placeholder="记录人工修改依据、来源冲突或批准理由"
            ></textarea>
          </div>

          <label>
            <input
              id="acknowledgeWarnings"
              type="checkbox"
              style="width:auto"
              ${
                confirmationWarnings.length
                  ? ""
                  : "checked disabled"
              }
            >
            ${
              confirmationWarnings.length
                ? "我已检查并接受需要人工确认的内容"
                : "当前没有需要确认的内容"
            }
          </label>

          <div
            class="toolbar"
            style="margin-top:14px"
          >
            <button
              type="button"
              class="success"
              onclick="approveItem()"
              ${canApprove ? "" : "disabled"}
            >
              批准导入
            </button>

            <button
              type="button"
              class="primary"
              onclick="importItem()"
              ${canImport ? "" : "disabled"}
            >
              导入 Mealie
            </button>
          </div>
        </div>
      </div>

      <div class="card danger-zone">
        <h3>拒绝此菜谱</h3>

        <div class="field">
          <label>拒绝原因</label>

          <textarea
            id="rejectReason"
            placeholder="例如：来源内容不完整、配方明显错误、重复菜谱"
          ></textarea>
        </div>

        <button
          type="button"
          class="danger"
          onclick="rejectItem()"
          ${canReject ? "" : "disabled"}
        >
          拒绝
        </button>
      </div>

      <div class="card">
        <h3>操作结果</h3>

        <pre
          id="result"
          class="result"
        >等待操作。</pre>
      </div>
    `;

    restoreResult();
  }

  async function retryCurrentItem() {
    const item = state.currentItem;

    if (!item) {
      return;
    }

    const button = document.getElementById(
      "retryItemButton"
    );

    const message = document.getElementById(
      "retryItemMessage"
    );

    if (
      !confirm(
        `确认将“${
          item.source_title
          ?? `Item #${item.id}`
        }”放回待处理队列？`
      )
    ) {
      return;
    }

    if (button) {
      button.disabled = true;
      button.textContent = "正在重置……";
    }

    if (message) {
      message.textContent =
        "正在将失败项目放回 queued……";
      message.style.color =
        "var(--muted)";
    }

    try {
      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${item.id}/retry`,
        {
          method: "POST",
        }
      );

      state.jobActionMessage =
        "项目已放回 queued。"
        + "现在点击“处理下一道”重新调用 Ollama。";

      state.jobActionIsError = false;

      await loadJobs();

      state.currentJobId =
        Number(data.job_id);

      const jobSelect =
        document.getElementById(
          "jobSelect"
        );

      if (jobSelect) {
        jobSelect.value =
          String(data.job_id);
      }

      await loadItems(
        Number(data.job_id)
      );

      await loadItem(
        Number(data.item_id)
      );

    } catch (error) {
      if (message) {
        message.textContent =
          error.message;
        message.style.color =
          "var(--danger)";
      }

      if (button) {
        button.disabled = false;
        button.textContent =
          "重试 AI 标准化";
      }
    }
  }


  async function processCurrentQueuedItem() {
    const item = state.currentItem;
    if (!item || item.status !== "queued") {
      return;
    }
    if (!confirm(
      `确认调用 Ollama 处理 Item #${item.id}？`
    )) {
      return;
    }
    const button = document.getElementById(
      "processItemButton"
    );
    if (button) {
      button.disabled = true;
      button.textContent = "正在处理……";
    }
    try {
      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${item.id}/process`,
        {
          method: "POST",
          body: JSON.stringify({
            confirm_item_id: Number(item.id),
            auto_import: false,
            unload_model_after: true,
          }),
        }
      );
      state.jobActionMessage =
        `Item #${item.id} 处理完成，已进入人工审核。`;
      state.jobActionIsError = false;
      await loadJobs();
      await loadItems(state.currentJobId);
      await loadItem(Number(item.id));
      showResult(data);
    } catch (error) {
      showResult(error.message, true);
      await loadJobs();
      await loadItems(state.currentJobId);
      await loadItem(Number(item.id));
    }
  }


  function addIngredient() {
    document.getElementById(
      "ingredients"
    ).insertAdjacentHTML(
      "beforeend",
      ingredientRow()
    );
  }

  function addInstruction() {
    const container =
      document.getElementById(
        "instructions"
      );

    const count =
      container.querySelectorAll(
        ".instruction-row"
      ).length;

    container.insertAdjacentHTML(
      "beforeend",
      instructionRow({
        step_number: count + 1,
        text: "",
      })
    );
  }

  function collectRecipe() {
    const original =
      structuredClone(
        state.currentItem.normalized
      );

    original.name =
      document.getElementById(
        "recipeName"
      ).value.trim();

    original.description =
      document.getElementById(
        "recipeDescription"
      ).value.trim();

    original.cuisine =
      document.getElementById(
        "recipeCuisine"
      ).value.trim();

    original.categories = splitList(
      document.getElementById(
        "recipeCategories"
      ).value
    );

    original.tags = splitList(
      document.getElementById(
        "recipeTags"
      ).value
    );

    original.servings = numericOrNull(
      document.getElementById(
        "recipeServings"
      ).value
    );

    original.prep_time_minutes =
      numericOrNull(
        document.getElementById(
          "recipePrepTime"
        ).value
      );

    original.cook_time_minutes =
      numericOrNull(
        document.getElementById(
          "recipeCookTime"
        ).value
      );

    original.total_time_minutes =
      numericOrNull(
        document.getElementById(
          "recipeTotalTime"
        ).value
      );

    original.ingredients = [
      ...document.querySelectorAll(
        ".ingredient-row"
      ),
    ].map((row) => {
      const originalIndex = Number(
        row.dataset.originalIndex
      );

      const previous =
        originalIndex >= 0
          ? state.currentItem.normalized
              .ingredients[originalIndex]
          : {};

      const foodName =
        row.querySelector(
          ".ingredient-food"
        ).value.trim();

      const amountMode =
        row.querySelector(
          ".ingredient-amount-mode"
        ).value;

      return {
        food_name: foodName,

        quantity: numericOrNull(
          row.querySelector(
            ".ingredient-quantity"
          ).value
        ),

        quantity_max: numericOrNull(
          row.querySelector(
            ".ingredient-quantity-max"
          ).value
        ),

        unit:
          row.querySelector(
            ".ingredient-unit"
          ).value.trim() || null,

        amount_mode: amountMode,

        role:
          row.querySelector(
            ".ingredient-role"
          ).value,

        note:
          row.querySelector(
            ".ingredient-note"
          ).value.trim() || null,

        original_text:
          previous.original_text
          || foodName
          || "人工添加食材",

        optional:
          row.querySelector(
            ".ingredient-optional"
          ).checked,
      };
    });

    original.instructions = [
      ...document.querySelectorAll(
        ".instruction-row"
      ),
    ].map((row, index) => {
      const stepNumber =
        numericOrNull(
          row.querySelector(
            ".instruction-number"
          ).value
        )
        ?? index + 1;

      const timers = [
        ...row.querySelectorAll(
          ".timer-row"
        ),
      ].map((timerRowElement) => {
        const kind =
          timerRowElement.querySelector(
            ".timer-kind"
          ).value;

        const minimum = numericOrNull(
          timerRowElement.querySelector(
            ".timer-minimum"
          ).value
        );

        const maximum = numericOrNull(
          timerRowElement.querySelector(
            ".timer-maximum"
          ).value
        );

        const unit =
          timerRowElement.querySelector(
            ".timer-unit"
          ).value;

        const multiplier =
          durationMultiplier(unit);

        const accepted =
          timerRowElement.querySelector(
            ".timer-accepted"
          ).checked;

        const source = accepted
          ? "manual"
          : (
              timerRowElement.dataset.source
              || "automatic"
            );

        return {
          name:
            timerRowElement.querySelector(
              ".timer-name"
            ).value.trim()
            || `步骤 ${stepNumber} 计时器`,

          kind,

          duration_seconds:
            kind === "fixed"
            && minimum != null
              ? Math.round(
                  minimum * multiplier
                )
              : null,

          duration_min_seconds:
            kind === "range"
            && minimum != null
              ? Math.round(
                  minimum * multiplier
                )
              : null,

          duration_max_seconds:
            kind === "range"
            && maximum != null
              ? Math.round(
                  maximum * multiplier
                )
              : null,

          source,
          accepted,
        };
      });

      return {
        step_number: stepNumber,

        text:
          row.querySelector(
            ".instruction-text"
          ).value.trim(),

        timers,
      };
    });

    if (!original.name) {
      throw new Error(
        "菜谱名称不能为空"
      );
    }

    for (
      const [index, ingredient]
      of original.ingredients.entries()
    ) {
      if (!ingredient.food_name) {
        throw new Error(
          `第 ${index + 1} 项食材名称不能为空`
        );
      }
    }

    for (
      const [index, instruction]
      of original.instructions.entries()
    ) {
      if (!instruction.text) {
        throw new Error(
          `第 ${index + 1} 个步骤不能为空`
        );
      }
    }

    return original;
  }

  function setActionFeedback(
    text,
    isError = false
  ) {
    const target = document.getElementById(
      "actionFeedback"
    );

    if (!target) {
      return;
    }

    target.textContent = text;
    target.style.color = isError
      ? "var(--danger)"
      : "var(--success)";
  }

  function resultSummary(
    value,
    isError
  ) {
    if (isError) {
      return "操作失败，详情见下方。";
    }

    if (
      value
      && typeof value === "object"
    ) {
      if (
        value.item_status === "imported"
      ) {
        return "已经成功导入 Mealie。";
      }

      if (
        value.item_status
        === "approved_for_import"
      ) {
        return "已经批准，可以导入 Mealie。";
      }

      if (
        typeof value.message === "string"
        && value.message
      ) {
        return value.message;
      }
    }

    return "操作完成，状态已经刷新。";
  }

  function restoreResult() {
    if (state.lastResult === null) {
      return;
    }

    showResult(
      state.lastResult,
      state.lastResultIsError
    );
  }

  function showResult(
    value,
    isError = false
  ) {
    state.lastResult = value;
    state.lastResultIsError = isError;

    setActionFeedback(
      resultSummary(
        value,
        isError
      ),
      isError
    );

    const target = document.getElementById(
      "result"
    );

    if (!target) {
      return;
    }

    target.style.color = isError
      ? "#ffb7b2"
      : "#f4eee5";

    target.textContent =
      typeof value === "string"
        ? value
        : formatJson(value);
  }

  async function saveItem() {
    setActionFeedback(
      "正在保存修改……"
    );

    try {
      const recipe = collectRecipe();

      const note =
        document.getElementById(
          "reviewNote"
        ).value.trim();

      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${
          state.currentItem.id
        }`,
        {
          method: "PATCH",
          body: JSON.stringify({
            normalized: recipe,
            review_note: note || null,
          }),
        }
      );

      showResult(data);

      await loadItems(
        state.currentJobId
      );

    } catch (error) {
      showResult(
        error.message,
        true
      );
    }
  }

  async function saveAndRevalidateItem() {
    setActionFeedback(
      "正在保存并重新校验……"
    );

    try {
      const recipe = collectRecipe();

      const note =
        document.getElementById(
          "reviewNote"
        ).value.trim();

      await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${
          state.currentItem.id
        }`,
        {
          method: "PATCH",
          body: JSON.stringify({
            normalized: recipe,
            review_note: note || null,
          }),
        }
      );

      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${
          state.currentItem.id
        }/revalidate`,
        {
          method: "POST",
        }
      );

      showResult(data);

      await loadItems(
        state.currentJobId
      );

    } catch (error) {
      showResult(
        error.message,
        true
      );
    }
  }

  async function revalidateItem() {
    setActionFeedback(
      "正在重新校验……"
    );

    try {
      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${
          state.currentItem.id
        }/revalidate`,
        {
          method: "POST",
        }
      );

      showResult(data);

      await loadItems(
        state.currentJobId
      );

    } catch (error) {
      showResult(
        error.message,
        true
      );
    }
  }

  async function approveItem() {
    setActionFeedback(
      "正在批准菜谱……"
    );

    try {
      const note =
        document.getElementById(
          "reviewNote"
        ).value.trim();

      const warningCheckbox =
        document.getElementById(
          "acknowledgeWarnings"
        );

      const currentWarnings =
        Array.isArray(
          state.currentItem
            ?.normalized
            ?.warnings
        )
          ? state.currentItem
              .normalized
              .warnings
          : [];

      const blocking = currentWarnings.filter(
        (warning) =>
          String(warning).startsWith(
            "[必须修正]"
          )
      );

      const confirmations =
        currentWarnings.filter(
          (warning) =>
            (
              String(warning).startsWith(
                "[需要确认]"
              )
              || String(warning).startsWith(
                "[系统校验]"
              )
            )
            && !isIgnorableTimerWarning(
              warning
            )
        );

      if (blocking.length > 0) {
        showResult(
          {
            message:
              "仍有必须修正的问题，不能批准。",
            blocking_warnings:
              blocking,
          },
          true
        );

        return;
      }

      if (
        confirmations.length > 0
        && !warningCheckbox.checked
      ) {
        showResult(
          {
            message:
              "仍有需要人工确认的内容。",
            warnings:
              confirmations,
          },
          true
        );

        warningCheckbox.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });

        return;
      }

      const acknowledge = (
        confirmations.length === 0
        || warningCheckbox.checked
      );

      const name =
        document.getElementById(
          "recipeName"
        ).value.trim();

      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${
          state.currentItem.id
        }/approve-for-import`,
        {
          method: "POST",
          body: JSON.stringify({
            confirm_name: name,
            acknowledge_warnings:
              acknowledge,
            review_note: note || null,
          }),
        }
      );

      showResult(data);

      await loadItems(
        state.currentJobId
      );

    } catch (error) {
      showResult(
        error.message,
        true
      );
    }
  }

  async function importItem() {
    const name =
      state.currentItem.normalized.name;

    const confirmed = confirm(
      `确认将“${name}”写入 Mealie？`
    );

    if (!confirmed) {
      return;
    }

    setActionFeedback(
      "正在写入 Mealie……"
    );

    try {
      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${
          state.currentItem.id
        }/import-to-mealie`,
        {
          method: "POST",
          body: JSON.stringify({
            confirm_item_id:
              state.currentItem.id,
            confirm_name: name,
          }),
        }
      );

      const importedItemId =
        Number(state.currentItem.id);

      showResult(data);

      await loadItems(
        state.currentJobId
      );

      const nextReview = state.items.find(
        (item) =>
          item.status === "review"
          && Number(item.id)
          !== importedItemId
      );

      if (nextReview) {
        state.jobActionMessage =
          "上一道已成功导入 Mealie；"
          + "已打开下一道待审核菜谱。";

        state.jobActionIsError = false;

        await loadItem(
          Number(nextReview.id)
        );
      }

    } catch (error) {
      showResult(
        error.message,
        true
      );
    }
  }

  async function nativePreview() {
    setActionFeedback(
      "正在生成原生结构预览……"
    );

    try {
      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${
          state.currentItem.id
        }/native-structure-preview`
      );

      showResult(data);

    } catch (error) {
      showResult(
        error.message,
        true
      );
    }
  }

  async function rejectItem() {
    const reason =
      document.getElementById(
        "rejectReason"
      ).value.trim();

    if (reason.length < 2) {
      showResult(
        "请输入拒绝原因。",
        true
      );
      return;
    }

    if (
      !confirm(
        `确认拒绝“${
          state.currentItem.normalized.name
        }”？`
      )
    ) {
      return;
    }

    setActionFeedback(
      "正在拒绝菜谱……"
    );

    try {
      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${
          state.currentItem.id
        }/reject`,
        {
          method: "POST",
          body: JSON.stringify({
            reason,
          }),
        }
      );

      showResult(data);

      await loadItems(
        state.currentJobId
      );

    } catch (error) {
      showResult(
        error.message,
        true
      );
    }
  }


  async function restoreRejectedItem() {
    const item = state.currentItem;
    if (!item || item.status !== "rejected") {
      return;
    }
    if (!confirm(
      `确认撤销 Item #${item.id} 的拒绝状态并恢复到人工审核？`
    )) {
      return;
    }
    setActionFeedback("正在恢复审核……");
    try {
      const data = await api(
        `/api/v1/import-jobs/${
          state.currentJobId
        }/items/${item.id}/restore-rejected`,
        {
          method: "POST",
          body: JSON.stringify({
            confirm_item_id: Number(item.id),
          }),
        }
      );
      await loadJobs();
      await loadItems(state.currentJobId);
      await loadItem(Number(item.id));
      showResult(data);
    } catch (error) {
      showResult(error.message, true);
    }
  }

  refreshAll();
</script>
</body>
</html>
'''
