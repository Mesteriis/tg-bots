      if (!window.Vue) {
        throw new Error("Vue runtime is not loaded");
      }
      const { createApp, nextTick } = Vue;
      createApp({
        data() {
          return {
            activeTab: "send",
            eventState: "connecting",
            botSaving: false,
            lastError: "",
            adminUiReady: false,
            adminAuthenticated: false,
            adminBusy: false,
            eventSource: null,
            navAccordionOpenId: "workflow",
            tabs: [
              { id: "send", label: "Отправка", icon: "send", description: "Главная консоль: ручной текст, шаблоны, batch и файлы из shared media." },
              { id: "bots", label: "Боты", icon: "bot", description: "Bot API токены, getMe, базовые сведения и готовность к отправке." },
              { id: "destinations", label: "Адресаты", icon: "send-to-back", description: "Группы, каналы, личные чаты и forum topic thread ID для повторной отправки." },
              { id: "templates", label: "Шаблоны", icon: "file-text", description: "Tagged-сообщения, форматирование Telegram, проверка и версии." },
              { id: "history", label: "Журнал", icon: "history", description: "История отправки, очередь, retry, dead-letter и Telegram response." },
              { id: "reliability", label: "Надежность", icon: "activity", description: "Живой граф очередей, rate limit, worker locks и результата отправки." },
              { id: "diagnostics", label: "ID-бот", icon: "scan-search", description: "Отдельный polling-бот, который красиво возвращает ID входящих и пересланных сообщений." },
              { id: "analytics", label: "Аналитика", icon: "chart-no-axes-combined", description: "Цели аналитики и ручной запуск refresh задач через Taskiq и Redis." },
              { id: "mtproto", label: "MTProto", icon: "smartphone", description: "Пользовательская Telegram-сессия для аналитики каналов и чатов через Telethon." },
              { id: "mcp", label: "MCP и API", icon: "plug-zap", description: "MCP transport, tool discovery, tg-like API и постоянные API-токены." },
              { id: "discovery", label: "Ops", icon: "radar", description: "Факты, рекомендации, автоматизация и MCP-покрытие операционного слоя Telegram." },
              { id: "audit", label: "Аудит", icon: "list-checks", description: "Операционный журнал административных действий и изменений доступа." },
              { id: "network", label: "Прокси / VPN", icon: "route", description: "Telegram-сеть: прямое подключение, WireGuard или OpenVPN." },
              { id: "operations", label: "Конфигурация", icon: "settings-2", description: "Поведение отправки, инфраструктура, бэкапы и восстановление без рестарта." },
              { id: "health", label: "Состояние", icon: "heart-pulse", description: "Runtime health, Bot API endpoint, shared media root и хранилище." },
            ],
            navGroups: [
              {
                id: "workflow",
                label: "Рабочий контур",
                description: "создать, выбрать, отправить",
                tabIds: ["send", "bots", "destinations", "templates", "history"],
              },
              {
                id: "control",
                label: "Контроль",
                description: "очереди, ID и аналитика",
                tabIds: ["reliability", "diagnostics", "analytics", "mtproto"],
              },
              {
                id: "integrations",
                label: "Интеграции",
                description: "AI, API и аудит",
                tabIds: ["mcp", "discovery", "audit"],
              },
              {
                id: "infrastructure",
                label: "Инфраструктура",
                description: "сеть, runtime и health",
                tabIds: ["network", "operations", "health"],
              },
            ],
            apiToken: localStorage.getItem("tgApiToken") || "",
            createdApiToken: "",
            adminState: {
              username: "admin",
              bootstrap_required: false,
              passkey_configured: false,
              auth_mode: "bootstrap",
            },
            adminPasskeys: [],
            passkeyBusy: false,
            passkeySupported:
              typeof window !== "undefined"
              && typeof window.PublicKeyCredential !== "undefined",
            bots: [], destinations: [], templates: [], sendProfiles: [], sendBatches: [], history: [], deadLetter: [], dueHistory: [], analyticsTargets: [], health: {},
            reliabilitySummary: { status_counts: {}, stale_locks: 0, degraded: false },
            reliabilityGraph: { nodes: [], edges: [] },
            reliabilityAttempts: [],
            reliabilityViewportWidth: typeof window === "undefined" ? 1280 : window.innerWidth,
            selectedReliabilityNode: "queue",
            reliabilityFallbackNodes: [
              { id: "source", label: "Batch / Manual", status: "ok", count: 0 },
              { id: "queue", label: "Queue", status: "ok", count: 0 },
              { id: "policy", label: "Policy gate", status: "ok", count: 0 },
              { id: "worker", label: "Worker lease", status: "ok", count: 0 },
              { id: "bot", label: "Bot bucket", status: "ok", count: 0 },
              { id: "chat", label: "Chat bucket", status: "ok", count: 0 },
              { id: "telegram", label: "Telegram", status: "ok", count: 0 },
              { id: "result", label: "Result", status: "ok", count: 0 },
            ],
            apiTokens: [],
            auditEvents: [],
            backupRuns: [],
            backupRepoCheck: null,
            backupPreflight: null,
            backupDiff: null,
            backupImport: { jsonText: "", confirm: "", preview: null, lastApply: null },
            restoreWizard: { runId: null, sections: ["templates"], confirm: "", preview: null, lastApply: null },
            sectionOptions: [
              { value: "bots", label: "Боты" },
              { value: "destinations", label: "Адресаты" },
              { value: "templates", label: "Шаблоны" },
              { value: "send_profiles", label: "Профили отправки" },
              { value: "mcp_settings", label: "MCP" },
              { value: "discovery_settings", label: "Автопоиск" },
              { value: "diagnostic_settings", label: "Диагностика" },
              { value: "api_tokens", label: "API токены" },
              { value: "runtime_settings", label: "Runtime" },
              { value: "runtime_advanced_settings", label: "Infra/advanced" },
            ],
            discoverySettings: [],
            activeOpsSubTab: "overview",
            opsFacts: [],
            opsRecommendations: [],
            opsRules: [],
            opsActionRuns: [],
            opsCoverage: { rows: [], missing_enabled_tools: [], missing_catalog_tools: [] },
            opsPreview: null,
            selectedOpsRecommendation: null,
            opsLastScan: null,
            diagnosticUpdates: [],
            destinationHealth: {},
            mcpConnectionInfo: null,
            operationsSettings: {},
            telegramEgressState: {
              mode: "direct",
              enabled: false,
              provider: null,
              provider_config_present: false,
              last_status: "disconnected",
              last_error: null,
              connected_at: null,
              last_handshake_at: null,
              last_egress_ip: null,
            },
            telegramEgressDraft: {
              mode: "direct",
              enabled: false,
              provider: null,
            },
            telegramEgressConfig: {
              provider: "wireguard",
              profile_text: "",
              auth_text: "",
            },
            telegramEgressStatus: null,
            operationsText: {
              cors_allowed_origins: "",
              mcp_allowed_origins: "",
              protected_api_hosts: "",
            },
            mediaItems: [],
            mediaPath: "",
            selectedSendProfileId: null,
            selectedTemplateId: null,
            templateVersions: [],
            botModalOpen: false,
            destinationModalOpen: false,
            analyticsModalOpen: false,
            apiTokenModalOpen: false,
            revokeTokenModalOpen: false,
            revokeTokenTarget: null,
            tokenRevocationBusy: false,
            sendDryRun: null,
            sendWorkTab: "quick",
            sendSubTab: "text",
            historySubTab: "all",
            mcpSubTab: "profile",
            operationsSubTab: "runtime",
            mtprotoStep: "phone",
            sendTargetMode: { text: "chat_id", template: "chat_id", file: "chat_id" },
            mtprotoStatus: { status: "missing", configured: false, api_credentials_missing: false, phone: null, last_error: null },
            templateSubTab: "saved",
            templateValidation: { variablesJson: "{}", result: null },
            parseModeOptions: [
              { key: "none", value: null, label: "без форматирования" },
              { key: "html", value: "HTML", label: "HTML" },
              { key: "markdown_v2", value: "MarkdownV2", label: "MarkdownV2" },
              { key: "markdown", value: "Markdown", label: "Markdown legacy" },
            ],
            tokenScopes: ["read", "send", "mcp_admin", "tg_compat", "ops_admin"],
            mcpSettings: { is_enabled: true, allow_legacy_sse: true, protected_hosts: ["tg.sh-inc.ru", "tg.sh-inc.dev"], transports: [], tools: [] },
            diagnosticSettings: { bot_id: null, bot_name: null, bot_username: null, is_enabled: false, last_update_id: null, last_error: null },
            forms: {
              adminLogin: { username: "admin", password: "12345678" },
              adminBootstrap: {
                current_username: "admin",
                current_password: "12345678",
                new_username: "",
                new_password: "",
                confirm_password: "",
              },
              adminChange: {
                current_password: "",
                new_username: "",
                new_password: "",
                confirm_password: "",
              },
              apiToken: { name: "dashboard", scopes: ["read", "send", "mcp_admin", "tg_compat", "ops_admin"] },
              bot: { name: "", token: "", description: "" },
              destination: { bot_id: null, kind: "channel", chat_id: "", message_thread_id: null, alias: "", title: "" },
              template: { tag: "", title: "", text: "", parse_mode: null, disable_web_page_preview: false },
              profile: { name: "" },
              batch: { name: "", destination_ids: [] },
              diagnosticDestination: { bot_id: null, alias: "" },
              send: { bot_id: null, destination_id: null, destination_alias: "", chat_id: "", tag: "", text: "", parse_mode: null, disable_web_page_preview: false, send_mode: "sync", send_at: "" },
              templateSend: { bot_id: null, destination_id: null, destination_alias: "", chat_id: "", tag: "", send_mode: "sync", send_at: "" },
              file: { bot_id: null, destination_id: null, destination_alias: "", chat_id: "", media_type: "video", file_relative_path: "", caption: "", parse_mode: null, send_mode: "sync", send_at: "" },
              mtproto: { phone: "", code: "", password: "" },
              analytics: { peer_ref: "", title: "" },
            },
          };
        },
        computed: {
          currentTab() { return this.tabs.find((tab) => tab.id === this.activeTab) || this.tabs[0]; },
          activeNavGroupId() {
            return this.navGroups.find((group) => group.tabIds.includes(this.activeTab))?.id || "workflow";
          },
          navSections() {
            return this.navGroups.map((group) => ({
              ...group,
              tabs: group.tabIds.map((id) => this.tabs.find((tab) => tab.id === id)).filter(Boolean),
            }));
          },
          workflowStats() {
            return [
              { label: "ботов", value: this.bots.length },
              { label: "адресатов", value: this.destinations.length },
              { label: "шаблонов", value: this.templates.length },
            ];
          },
          eventStateLabel() { return this.statusLabel(this.eventState); },
          adminSessionLabel() {
            if (!this.adminUiReady) return "сессия: проверка";
            if (this.adminAuthenticated) return `сессия: ${this.adminState.username}`;
            if (this.adminState.bootstrap_required) return "сессия: bootstrap";
            return "сессия: вход нужен";
          },
          mtprotoCredentialsConfigured() {
            return Boolean(this.mtprotoStatus.configured);
          },
          mtprotoStatusLabel() {
            return {
              config_missing: "нужны API credentials",
              missing: "не настроено",
              code_requested: "код отправлен",
              password_required: "нужен 2FA пароль",
              ready: "сессия готова",
              failed: "ошибка",
            }[this.mtprotoStatus.status] || this.statusLabel(this.mtprotoStatus.status);
          },
          fileSendAvailable() {
            return Boolean(this.health.local_bot_api && this.health.shared_media_available);
          },
          fileSendUnavailableReason() {
            const reasons = [];
            if (!this.health.local_bot_api) reasons.push("нужен локальный Telegram Bot API");
            if (this.health.shared_media_available === false) {
              reasons.push(this.health.shared_media_error || "shared media root недоступен");
            }
            if (this.health.shared_media_available == null && reasons.length === 0) {
              reasons.push("состояние shared media еще не загружено");
            }
            return reasons.join("; ");
          },
          backupRepoCheckLabel() {
            if (!this.backupRepoCheck) return "";
            const privacy = this.backupRepoCheck.verified
              ? (this.backupRepoCheck.is_private ? "private repo" : "public repo")
              : "privacy unknown";
            const auth = this.backupRepoCheck.auth_method === "token" ? "API token / PAT" : "без авторизации";
            return `${this.backupRepoCheck.service || "repo"}: ${privacy}; auth: ${auth}; ${this.backupRepoCheck.message}`;
          },
          restorableBackupRuns() {
            return this.backupRuns.filter((run) => run.snapshot && ["succeeded", "pre_restore"].includes(run.status));
          },
          opsOpenRecommendations() {
            return this.opsRecommendations.filter((item) => item.status === "open");
          },
          opsCoverageRows() {
            return Array.isArray(this.opsCoverage?.rows) ? this.opsCoverage.rows : [];
          },
          opsMissingEnabledTools() {
            return Array.isArray(this.opsCoverage?.missing_enabled_tools) ? this.opsCoverage.missing_enabled_tools : [];
          },
          opsMissingCatalogTools() {
            return Array.isArray(this.opsCoverage?.missing_catalog_tools) ? this.opsCoverage.missing_catalog_tools : [];
          },
          rowDiffRows() {
            return this.restoreWizard.preview?.diff?.rows || [];
          },
          historyStatusCounts() {
            const counts = { succeeded: 0, failed: 0, queued: 0, dead_letter: this.deadLetter.length };
            this.history.forEach((item) => {
              if (item.status === "succeeded") counts.succeeded += 1;
              if (item.status === "failed") counts.failed += 1;
              if (["queued", "created", "deferred"].includes(item.status)) counts.queued += 1;
            });
            return counts;
          },
          historyStatusTotal() {
            return Math.max(1, this.history.length + this.deadLetter.length);
          },
          isProtectedHost() { return ["tg.sh-inc.ru", "tg.sh-inc.dev"].includes(window.location.hostname); },
          dashboardApiReady() {
            return this.adminAuthenticated && (!this.isProtectedHost || Boolean(this.apiToken));
          },
          passkeyOriginSupported() {
            const host = typeof window === "undefined" ? "" : window.location.hostname;
            const protocol = typeof window === "undefined" ? "" : window.location.protocol;
            return protocol === "https:" || host === "localhost";
          },
          passkeyOriginHint() {
            if (typeof window === "undefined") return "";
            if (window.location.protocol === "https:") {
              return "HTTPS origin подходит для passkey и iPhone.";
            }
            if (window.location.hostname === "localhost") {
              return "Для локального Touch ID origin подходит.";
            }
            return "Для локального Touch ID открой админку через http://localhost:8000. Для iPhone нужен HTTPS-домен.";
          },
          currentOrigin() {
            return typeof window === "undefined" ? "-" : window.location.origin;
          },
          currentRpId() {
            return typeof window === "undefined" ? "-" : window.location.hostname;
          },
        },
        async mounted() {
          this.updateViewportMetrics();
          window.addEventListener("resize", this.updateViewportMetrics);
          if (this.apiToken) {
            await this.establishApiSession().catch((error) => {
              this.lastError = error.message;
            });
          }
          await this.loadAdminState().catch((error) => {
            this.lastError = error.message;
          });
          this.adminUiReady = true;
          if (this.dashboardApiReady) {
            await this.refreshAll().catch((error) => { this.lastError = error.message; });
            this.connectEvents();
          }
          this.drawIcons();
        },
        beforeUnmount() {
          window.removeEventListener("resize", this.updateViewportMetrics);
          this.disconnectEvents();
        },
        updated() { this.drawIcons(); },
        methods: {
          drawIcons() {
            nextTick(() => {
              if (window.lucide?.createIcons) {
                window.lucide.createIcons({ attrs: { width: 16, height: 16 } });
              }
            });
          },
          updateViewportMetrics() {
            this.reliabilityViewportWidth = typeof window === "undefined" ? 1280 : (window.innerWidth || 1280);
          },
          isNavGroupOpen(group) {
            return (this.navAccordionOpenId || this.activeNavGroupId) === group.id;
          },
          toggleNavGroup(group) {
            this.navAccordionOpenId = group.id;
          },
          selectTab(tabId) {
            this.activeTab = tabId;
            const group = this.navGroups.find((item) => item.tabIds.includes(tabId));
            if (group) this.navAccordionOpenId = group.id;
          },
          boolLabel(value) { return value ? "да" : "нет"; },
          formatBytes(value) {
            if (!Number.isFinite(Number(value))) return "-";
            const units = ["B", "KB", "MB", "GB"];
            let size = Number(value);
            let unit = 0;
            while (size >= 1024 && unit < units.length - 1) {
              size /= 1024;
              unit += 1;
            }
            return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
          },
          parseCsv(value) {
            return String(value || "")
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean);
          },
          syncOperationsText() {
            this.operationsText = {
              cors_allowed_origins: (this.operationsSettings.cors_allowed_origins || []).join(", "),
              mcp_allowed_origins: (this.operationsSettings.mcp_allowed_origins || []).join(", "),
              protected_api_hosts: (this.operationsSettings.protected_api_hosts || []).join(", "),
            };
          },
          syncTelegramEgressDraft() {
            this.telegramEgressDraft = {
              mode: this.telegramEgressState.mode || "direct",
              enabled: Boolean(this.telegramEgressState.enabled),
              provider: this.telegramEgressState.provider,
            };
            this.normalizeTelegramEgressDraft();
          },
          normalizeTelegramEgressDraft() {
            if (this.telegramEgressDraft.mode === "direct") {
              this.telegramEgressDraft.provider = null;
            } else if (
              !this.telegramEgressDraft.provider
              || this.telegramEgressDraft.provider !== this.telegramEgressDraft.mode
            ) {
              this.telegramEgressDraft.provider = this.telegramEgressDraft.mode;
            }
            this.telegramEgressConfig.provider = this.telegramEgressDraft.mode === "direct"
              ? "wireguard"
              : this.telegramEgressDraft.mode;
            if (this.telegramEgressDraft.mode === "wireguard") {
              this.telegramEgressConfig.auth_text = "";
            }
          },
          categoryLabel(value) {
            return {
              read: "чтение",
              send: "отправка",
              task: "задачи",
              security: "безопасность",
            }[value] || value;
          },
          kindLabel(value) {
            return {
              private: "личный чат",
              group: "группа",
              supergroup: "супергруппа",
              channel: "канал",
              forum_topic: "тема форума",
            }[value] || value;
          },
          riskLabel(value) {
            return {
              read: "чтение",
              write: "запись",
              admin: "админ",
            }[value] || value;
          },
          profileKindLabel(value) {
            return {
              text: "текст",
              template: "шаблон",
              file: "файл",
            }[value] || value;
          },
          scopeLabel(value) {
            return {
              read: "чтение",
              send: "отправка",
              mcp_admin: "админ MCP",
              tg_compat: "TG API",
              ops_admin: "Telegram Ops",
            }[value] || value;
          },
          statusLabel(value) {
            return {
              active: "активен",
              closed: "нет связи",
              connecting: "подключение",
              created: "создано",
              failed: "ошибка",
              finished: "завершено",
              live: "онлайн",
              queued: "в очереди",
              blocked: "заблокировано",
              deferred: "отложено",
              dead_letter: "dead-letter",
              locked: "lock занят",
              released: "освобождено",
              retry_scheduled: "повтор запланирован",
              warning: "внимание",
              revoked: "отозван",
              started: "запущено",
              succeeded: "успешно",
              ok: "ok",
              disconnected: "отключено",
              misconfigured: "не настроено",
              not_applicable: "не применимо",
              connected: "подключено",
              degraded: "деградировано",
              config_missing: "нужны API credentials",
              code_requested: "код отправлен",
              password_required: "нужен 2FA пароль",
              "не запускался": "не запускался",
            }[value] || value;
          },
          backupSecretsLabel(policy) {
            if (!policy) return "-";
            if (policy.include_secrets && policy.secret_reason === "private_repo") return "да, private repo";
            if (policy.include_secrets && policy.secret_reason === "manual_setting") return "да, вручную";
            return "нет";
          },
          backupRepoLabel(repo) {
            if (!repo) return "-";
            const service = repo.service || "unknown";
            const privacy = repo.verified
              ? (repo.is_private ? "private" : "public")
              : "unknown";
            return `${service}: ${privacy}`;
          },
          restoreRunLabel(run) {
            const created = run.created_at ? new Date(run.created_at).toLocaleString("ru-RU") : "-";
            return `#${run.id} · ${this.statusLabel(run.status)} · ${created} · ${run.items_exported} строк`;
          },
          diffActionLabel(action) {
            return {
              added: "добавится",
              removed: "удалится",
              changed: "изменится",
            }[action] || action;
          },
          shortJson(value) {
            if (value == null) return "-";
            const raw = JSON.stringify(value, null, 2);
            return raw.length > 640 ? `${raw.slice(0, 640)}...` : raw;
          },
          formatDate(value) {
            return value ? new Date(value).toLocaleString("ru-RU") : "-";
          },
          formatOpsValue(value) {
            if (value == null || value === "") return "-";
            if (Array.isArray(value)) return value.length ? value.map((item) => this.formatOpsValue(item)).join(", ") : "-";
            if (typeof value === "object") return JSON.stringify(value);
            return String(value);
          },
          opsDiffRows(diff) {
            if (!diff || typeof diff !== "object") return [{ key: "diff", value: "-" }];
            if (Array.isArray(diff.rows)) {
              return diff.rows.map((row, index) => ({
                key: row.field || row.key || row.name || `row_${index + 1}`,
                value: [row.action, row.before, row.after, row.value]
                  .filter((item) => item != null && item !== "")
                  .map((item) => this.formatOpsValue(item))
                  .join(" → ") || "-",
              }));
            }
            const preferred = ["operation", "entity", "destination", "fields", "changes"];
            const keys = [...preferred.filter((key) => key in diff), ...Object.keys(diff).filter((key) => !preferred.includes(key))];
            return keys.map((key) => ({ key, value: this.formatOpsValue(diff[key]) }));
          },
          opsToolList(value) {
            return Array.isArray(value) && value.length ? value.join(", ") : "-";
          },
          opsCoverageCapabilities(row) {
            const parts = [];
            if (row.rest) parts.push(`REST: ${this.formatOpsValue(row.rest)}`);
            if (row.ui) parts.push(`UI: ${this.formatOpsValue(row.ui)}`);
            if (row.mcp_read_tools?.length) parts.push(`read: ${row.mcp_read_tools.join(", ")}`);
            if (row.mcp_preview_tools?.length) parts.push(`preview: ${row.mcp_preview_tools.join(", ")}`);
            if (row.mcp_apply_tools?.length) parts.push(`apply: ${row.mcp_apply_tools.join(", ")}`);
            if (row.required_scopes?.length) parts.push(`scopes: ${row.required_scopes.join(", ")}`);
            return parts.join(" · ") || "-";
          },
          opsResultSummary(result) {
            if (!result || typeof result !== "object") return "-";
            return Object.entries(result)
              .map(([key, value]) => `${key}: ${this.formatOpsValue(value)}`)
              .join("; ") || "-";
          },
          batchProgressLabel(progress) {
            if (!progress) return "-";
            return `всего ${progress.total || 0}, pending ${progress.pending || 0}, queued ${progress.queued || 0}, ok ${progress.succeeded || 0}, fail ${progress.failed || 0}`;
          },
          templateValidationError(message) {
            if (message === "invalid template placeholder syntax; use {{name}}") {
              return "Некорректный плейсхолдер. Используй формат {{name}}.";
            }
            if (message.startsWith("missing template variables:")) {
              return "Не хватает проверочных переменных.";
            }
            return message;
          },
          disconnectEvents() {
            if (this.eventSource) {
              this.eventSource.close();
              this.eventSource = null;
            }
          },
          async adminFetch(path, options = {}) {
            const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
            if (this.apiToken) headers["X-API-Token"] = this.apiToken;
            const response = await fetch(`/api/v1${path}`, {
              ...options,
              headers,
              credentials: "same-origin",
            });
            if (!response.ok) {
              let detail = await response.text();
              try {
                detail = JSON.parse(detail).detail || detail;
              } catch {
                // Keep the raw response text for non-JSON errors.
              }
              this.lastError = detail;
              throw new Error(detail);
            }
            this.lastError = "";
            if (response.status === 204) return null;
            return response.json();
          },
          async loadAdminState() {
            const state = await this.adminFetch("/auth/admin/state");
            this.adminState = state;
            this.adminAuthenticated = Boolean(state.authenticated);
            this.forms.adminLogin.username = state.username || "admin";
            if (state.authenticated && !state.bootstrap_required) {
              this.forms.adminChange.new_username = state.username;
              await this.refreshAdminPasskeys();
              return;
            }
            this.adminPasskeys = [];
          },
          async refreshAdminPasskeys() {
            if (!this.adminAuthenticated || this.adminState.bootstrap_required) {
              this.adminPasskeys = [];
              return;
            }
            this.adminPasskeys = await this.adminFetch("/auth/admin/passkeys");
          },
          async loginAdmin() {
            this.adminBusy = true;
            try {
              const state = await this.adminFetch("/auth/admin/login", {
                method: "POST",
                body: JSON.stringify(this.forms.adminLogin),
              });
              this.adminState = state;
              this.adminAuthenticated = Boolean(state.authenticated);
              if (this.dashboardApiReady) {
                await this.refreshAll();
                this.connectEvents();
              }
              await this.loadAdminState();
            } catch (error) {
              this.lastError = error instanceof Error ? error.message : "Вход не выполнен";
            } finally {
              this.adminBusy = false;
            }
          },
          async bootstrapAdmin() {
            this.adminBusy = true;
            try {
              if (this.forms.adminBootstrap.new_password !== this.forms.adminBootstrap.confirm_password) {
                throw new Error("Новый пароль и подтверждение не совпадают");
              }
              await this.adminFetch("/auth/admin/bootstrap", {
                method: "POST",
                body: JSON.stringify({
                  current_username: this.forms.adminBootstrap.current_username,
                  current_password: this.forms.adminBootstrap.current_password,
                  new_username: this.forms.adminBootstrap.new_username,
                  new_password: this.forms.adminBootstrap.new_password,
                }),
              });
              this.forms.adminLogin.username = this.forms.adminBootstrap.new_username;
              this.forms.adminLogin.password = "";
              this.forms.adminChange = {
                current_password: "",
                new_username: this.forms.adminBootstrap.new_username,
                new_password: "",
                confirm_password: "",
              };
              await this.loadAdminState();
              if (this.dashboardApiReady) {
                await this.refreshAll();
                this.connectEvents();
              }
            } catch (error) {
              this.lastError = error instanceof Error ? error.message : "Первая настройка не выполнена";
            } finally {
              this.adminBusy = false;
            }
          },
          async logoutAdmin() {
            this.adminBusy = true;
            try {
              await this.adminFetch("/auth/admin/logout", { method: "POST" });
              this.disconnectEvents();
              this.adminAuthenticated = false;
              await this.loadAdminState();
            } finally {
              this.adminBusy = false;
            }
          },
          async changeAdminCredentials() {
            this.adminBusy = true;
            try {
              if (this.forms.adminChange.new_password !== this.forms.adminChange.confirm_password) {
                throw new Error("Новый пароль и подтверждение не совпадают");
              }
              if (!confirm("Обновить логин и пароль администратора? Текущая browser-сессия будет перевыпущена.")) {
                return;
              }
              const state = await this.adminFetch("/auth/admin/change", {
                method: "POST",
                body: JSON.stringify({
                  current_password: this.forms.adminChange.current_password,
                  new_username: this.forms.adminChange.new_username,
                  new_password: this.forms.adminChange.new_password,
                }),
              });
              this.adminState = state;
              this.forms.adminLogin.username = state.username;
              this.forms.adminChange.current_password = "";
              this.forms.adminChange.new_password = "";
              this.forms.adminChange.confirm_password = "";
              await this.loadAdminState();
            } catch (error) {
              this.lastError = error instanceof Error ? error.message : "Доступ не обновлен";
            } finally {
              this.adminBusy = false;
            }
          },
          base64urlToBuffer(value) {
            const normalized = `${value}`.replace(/-/g, "+").replace(/_/g, "/");
            const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
            const raw = atob(padded);
            const bytes = new Uint8Array(raw.length);
            for (let index = 0; index < raw.length; index += 1) {
              bytes[index] = raw.charCodeAt(index);
            }
            return bytes.buffer;
          },
          bufferToBase64url(buffer) {
            const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer || new ArrayBuffer(0));
            let raw = "";
            bytes.forEach((byte) => {
              raw += String.fromCharCode(byte);
            });
            return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
          },
          decodeCreationOptions(options) {
            return {
              ...options,
              challenge: this.base64urlToBuffer(options.challenge),
              user: {
                ...options.user,
                id: this.base64urlToBuffer(options.user.id),
              },
              excludeCredentials: (options.excludeCredentials || []).map((item) => ({
                ...item,
                id: this.base64urlToBuffer(item.id),
              })),
            };
          },
          decodeRequestOptions(options) {
            return {
              ...options,
              challenge: this.base64urlToBuffer(options.challenge),
              allowCredentials: (options.allowCredentials || []).map((item) => ({
                ...item,
                id: this.base64urlToBuffer(item.id),
              })),
            };
          },
          credentialToJson(credential) {
            const response = credential.response || {};
            const payload = {
              id: credential.id,
              rawId: this.bufferToBase64url(credential.rawId),
              type: credential.type,
              clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
              response: {},
            };
            if (response.attestationObject) {
              payload.response.attestationObject = this.bufferToBase64url(response.attestationObject);
            }
            if (response.clientDataJSON) {
              payload.response.clientDataJSON = this.bufferToBase64url(response.clientDataJSON);
            }
            if (response.authenticatorData) {
              payload.response.authenticatorData = this.bufferToBase64url(response.authenticatorData);
            }
            if (response.signature) {
              payload.response.signature = this.bufferToBase64url(response.signature);
            }
            if (response.userHandle) {
              payload.response.userHandle = this.bufferToBase64url(response.userHandle);
            }
            if (response.getTransports) {
              payload.response.transports = response.getTransports();
            }
            return payload;
          },
          async beginPasskeyRegistration() {
            this.passkeyBusy = true;
            try {
              if (!this.passkeySupported) {
                throw new Error("Этот браузер не поддерживает passkey API");
              }
              if (!this.passkeyOriginSupported) {
                throw new Error(this.passkeyOriginHint);
              }
              const started = await this.adminFetch("/auth/admin/passkeys/register/options", {
                method: "POST",
                body: JSON.stringify({ label: "MacBook Touch ID" }),
              });
              const credential = await navigator.credentials.create({
                publicKey: this.decodeCreationOptions(JSON.parse(started.options_json)),
              });
              if (!credential) {
                throw new Error("Регистрация passkey была отменена");
              }
              await this.adminFetch("/auth/admin/passkeys/register/verify", {
                method: "POST",
                body: JSON.stringify({
                  challenge_id: started.challenge_id,
                  credential: this.credentialToJson(credential),
                }),
              });
              await this.loadAdminState();
            } catch (error) {
              this.lastError = error instanceof Error ? error.message : "Passkey не добавлен";
            } finally {
              this.passkeyBusy = false;
            }
          },
          async loginWithPasskey() {
            this.passkeyBusy = true;
            try {
              if (!this.passkeySupported) {
                throw new Error("Этот браузер не поддерживает passkey API");
              }
              if (!this.passkeyOriginSupported) {
                throw new Error(this.passkeyOriginHint);
              }
              const started = await this.adminFetch("/auth/admin/passkeys/auth/options", {
                method: "POST",
              });
              const credential = await navigator.credentials.get({
                publicKey: this.decodeRequestOptions(JSON.parse(started.options_json)),
              });
              if (!credential) {
                throw new Error("Вход по passkey был отменен");
              }
              const state = await this.adminFetch("/auth/admin/passkeys/auth/verify", {
                method: "POST",
                body: JSON.stringify({
                  challenge_id: started.challenge_id,
                  credential: this.credentialToJson(credential),
                }),
              });
              this.adminState = state;
              this.adminAuthenticated = Boolean(state.authenticated);
              await this.loadAdminState();
              if (this.dashboardApiReady) {
                await this.refreshAll();
                this.connectEvents();
              }
            } catch (error) {
              this.lastError = error instanceof Error ? error.message : "Вход по passkey не выполнен";
            } finally {
              this.passkeyBusy = false;
            }
          },
          async deletePasskey(credentialId, rpId) {
            if (!confirm("Удалить этот passkey? Повторный вход через Touch ID придется подключить заново.")) {
              return;
            }
            await this.adminFetch(`/auth/admin/passkeys/${encodeURIComponent(credentialId)}?rp_id=${encodeURIComponent(rpId)}`, {
              method: "DELETE",
            });
            await this.loadAdminState();
          },
          async api(path, options = {}) {
            const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
            if (this.apiToken) headers["X-API-Token"] = this.apiToken;
            const response = await fetch(`/api/v1${path}`, {
              ...options,
              headers,
              credentials: "same-origin",
            });
            if (!response.ok) {
              let detail = await response.text();
              try {
                detail = JSON.parse(detail).detail || detail;
              } catch {
                // Keep the raw response text for non-JSON errors.
              }
              if (response.status === 401 && detail === "admin session required") {
                this.disconnectEvents();
                this.adminAuthenticated = false;
                await this.loadAdminState().catch(() => {});
              }
              this.lastError = detail;
              throw new Error(detail);
            }
            this.lastError = "";
            if (response.status === 204) return null;
            return response.json();
          },
          async establishApiSession() {
            if (!this.apiToken) return;
            const response = await fetch("/api/v1/auth/session", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ token: this.apiToken }),
            });
            if (!response.ok) throw new Error("Неверный API-токен");
          },
          async saveApiToken() {
            localStorage.setItem("tgApiToken", this.apiToken);
            await this.establishApiSession();
            if (this.dashboardApiReady) {
              await this.refreshAll();
              this.connectEvents();
            }
          },
          clearApiToken() {
            this.apiToken = "";
            localStorage.removeItem("tgApiToken");
          },
          async refreshReliability() {
            if (!this.dashboardApiReady) return;
            const [summary, graph, attempts] = await Promise.all([
              this.api("/reliability/summary"),
              this.api("/reliability/graph"),
              this.api("/reliability/attempts"),
            ]);
            this.reliabilitySummary = summary;
            this.reliabilityGraph = graph;
            this.reliabilityAttempts = attempts;
          },
          async refreshOps() {
            if (!this.dashboardApiReady) return;
            const [opsFacts, opsRecommendations, opsRules, opsActionRuns, opsCoverage] = await Promise.all([
              this.api("/ops/facts"),
              this.api("/ops/recommendations"),
              this.api("/ops/rules"),
              this.api("/ops/action-runs"),
              this.api("/ops/mcp-coverage"),
            ]);
            Object.assign(this, {
              opsFacts,
              opsRecommendations,
              opsRules,
              opsActionRuns,
              opsCoverage: opsCoverage || { rows: [], missing_enabled_tools: [], missing_catalog_tools: [] },
            });
          },
          async refreshAll() {
            if (!this.dashboardApiReady) return;
            const [health, bots, destinations, templates, sendProfiles, sendBatches, history, deadLetter, dueHistory, mtprotoStatus, analyticsTargets, diagnosticSettings, diagnosticUpdates, mcpSettings, mcpConnectionInfo, apiTokens, discoverySettings, auditEvents, operationsSettings, telegramEgressState, backupRuns, reliabilitySummary, reliabilityGraph, reliabilityAttempts, opsFacts, opsRecommendations, opsRules, opsActionRuns, opsCoverage] = await Promise.all([
              this.api("/health"),
              this.api("/bots"),
              this.api("/destinations"),
              this.api("/templates"),
              this.api("/send-profiles"),
              this.api("/send-batches"),
              this.api("/send-history"),
              this.api("/send-history/dead-letter"),
              this.api("/send-history/due"),
              this.api("/mtproto/status"),
              this.api("/analytics/targets"),
              this.api("/diagnostics/bot"),
              this.api("/diagnostics/updates"),
              this.api("/mcp/settings"),
              this.api("/mcp/connection-info"),
              this.api("/auth/tokens"),
              this.api("/discovery/bots"),
              this.api("/audit"),
              this.api("/operations/settings"),
              this.api("/operations/telegram-egress"),
              this.api("/operations/backup/runs"),
              this.api("/reliability/summary"),
              this.api("/reliability/graph"),
              this.api("/reliability/attempts"),
              this.api("/ops/facts"),
              this.api("/ops/recommendations"),
              this.api("/ops/rules"),
              this.api("/ops/action-runs"),
              this.api("/ops/mcp-coverage"),
            ]);
            Object.assign(this, { health, bots, destinations, templates, sendProfiles, sendBatches, history, deadLetter, dueHistory, mtprotoStatus, analyticsTargets, diagnosticSettings, diagnosticUpdates, mcpSettings, mcpConnectionInfo, apiTokens, discoverySettings, auditEvents, operationsSettings, telegramEgressState, backupRuns, reliabilitySummary, reliabilityGraph, reliabilityAttempts, opsFacts, opsRecommendations, opsRules, opsActionRuns, opsCoverage: opsCoverage || { rows: [], missing_enabled_tools: [], missing_catalog_tools: [] } });
            this.syncOperationsText();
            this.syncTelegramEgressDraft();
            this.applyBackupServiceDefaults();
            this.syncMtprotoStepFromStatus(mtprotoStatus);
            if (this.sendSubTab === "file" && !this.fileSendAvailable) this.sendSubTab = "text";
            if (this.sendWorkTab === "file" && !this.fileSendAvailable) this.sendWorkTab = "quick";
          },
          syncMtprotoStepFromStatus(status) {
            if (!status || !status.status) {
              this.mtprotoStep = "phone";
              return;
            }
            if (status.status === "code_requested") {
              this.mtprotoStep = "code";
              return;
            }
            if (status.status === "password_required") {
              this.mtprotoStep = "password";
              return;
            }
            this.mtprotoStep = "phone";
          },
          selectReliabilityNode(id) {
            this.selectedReliabilityNode = id;
          },
          async releaseStaleLocks() {
            await this.api("/reliability/stale-locks/release", { method: "POST" });
            await this.refreshAll();
          },
          reliabilityNode(id) {
            return this.reliabilityGraph.nodes.find((node) => node.id === id)
              || this.reliabilityFallbackNodes.find((node) => node.id === id)
              || { id, label: id, status: "ok", count: 0 };
          },
          reliabilityNodes() {
            return this.reliabilityGraph.nodes.length ? this.reliabilityGraph.nodes : this.reliabilityFallbackNodes;
          },
          reliabilityGraphRows() {
            const nodes = this.reliabilityNodes();
            const perRow = this.reliabilityViewportWidth >= 1600
              ? 4
              : this.reliabilityViewportWidth >= 1180
                ? 3
                : this.reliabilityViewportWidth >= 860
                  ? 2
                  : 1;
            const rows = [];
            for (let offset = 0; offset < nodes.length; offset += perRow) {
              const sequenceNodes = nodes.slice(offset, offset + perRow);
              const forward = rows.length % 2 === 0;
              rows.push({
                forward,
                sequenceNodes,
                displayNodes: forward ? sequenceNodes : [...sequenceNodes].reverse(),
                entryNodeId: sequenceNodes[0]?.id || null,
                exitNodeId: sequenceNodes[sequenceNodes.length - 1]?.id || null,
              });
            }
            return rows;
          },
          reliabilityEdges() {
            if (this.reliabilityGraph.edges.length) {
              return this.reliabilityGraph.edges.map((edge) => ({
                from: edge.from || edge.source,
                to: edge.to || edge.target,
                count: edge.count ?? (edge.active ? 1 : 0),
                status: edge.status || "ok",
                active: Boolean(edge.active),
              }));
            }
            return this.reliabilityFallbackNodes.slice(0, -1).map((node, index) => ({
              from: node.id,
              to: this.reliabilityFallbackNodes[index + 1].id,
              count: 0,
              status: "ok",
              active: false,
            }));
          },
          reliabilityRowEdge(row, index) {
            if (index >= row.displayNodes.length - 1) return null;
            const current = row.displayNodes[index];
            const next = row.displayNodes[index + 1];
            const from = row.forward ? current.id : next.id;
            const to = row.forward ? next.id : current.id;
            const edge = this.reliabilityEdges().find((item) => item.from === from && item.to === to);
            return {
              from,
              to,
              count: edge?.count || 0,
              status: edge?.status || "ok",
              active: Boolean(edge?.active),
              direction: row.forward ? "forward" : "backward",
            };
          },
          reliabilityRowTurn(rowIndex) {
            const rows = this.reliabilityGraphRows();
            if (rowIndex >= rows.length - 1) return null;
            const current = rows[rowIndex];
            const next = rows[rowIndex + 1];
            const from = current.exitNodeId;
            const to = next.entryNodeId;
            if (!from || !to) return null;
            const edge = this.reliabilityEdges().find((item) => item.from === from && item.to === to);
            return {
              from,
              to,
              count: edge?.count || 0,
              status: edge?.status || "ok",
              active: Boolean(edge?.active),
              direction: "forward",
            };
          },
          reliabilityAttemptMatchesNode(attempt, nodeId) {
            const status = attempt.status || "";
            const errorKind = attempt.error_kind || "";
            if (["source", "queue", "worker", "result"].includes(nodeId)) return true;
            if (nodeId === "policy") {
              return ["deferred", "blocked", "dead_letter"].includes(status) || Boolean(errorKind);
            }
            if (nodeId === "bot" || nodeId === "chat") {
              return ["rate_limit", "telegram_rate_limit"].includes(errorKind);
            }
            if (nodeId === "telegram") {
              return status === "succeeded" || errorKind.startsWith("telegram_") || ["blocked", "dead_letter"].includes(status);
            }
            return true;
          },
          reliabilityAttemptsForNode(nodeId) {
            const matched = this.reliabilityAttempts.filter((attempt) => this.reliabilityAttemptMatchesNode(attempt, nodeId));
            return matched.length ? matched : this.reliabilityAttempts;
          },
          connectEvents() {
            if (!this.dashboardApiReady) return;
            this.disconnectEvents();
            const source = new EventSource("/api/v1/events");
            this.eventSource = source;
            source.onopen = () => { this.eventState = "live"; };
            source.onerror = () => { this.eventState = "closed"; };
            source.onmessage = () => this.refreshAll();
            ["send.created", "send.succeeded", "send.failed", "send.deferred", "send.dead_letter", "send.blocked", "send.locked", "send.released", "send.retry_scheduled", "analytics.run.queued", "analytics.run.finished", "bot.checked", "mtproto.login.status_changed"].forEach((name) => {
              source.addEventListener(name, () => this.refreshAll());
            });
            ["reliability.bucket.updated", "reliability.graph.updated"].forEach((name) => {
              source.addEventListener(name, () => this.refreshReliability());
            });
            ["ops.scan.completed", "ops.action.previewed", "ops.action.applied", "ops.recommendation.dismissed", "ops.rule.updated", "ops.rule.ran", "ops.rule.paused", "ops.rule.resumed"].forEach((name) => {
              source.addEventListener(name, () => this.refreshOps());
            });
          },
          async createBot() {
            this.botSaving = true;
            try {
              await this.api("/bots", { method: "POST", body: JSON.stringify(this.forms.bot) });
              this.forms.bot = { name: "", token: "", description: "" };
              this.lastError = "";
              this.closeBotModal();
              await this.refreshAll();
            } catch (error) {
              this.lastError = error instanceof Error ? error.message : "Запрос не выполнен";
            } finally {
              this.botSaving = false;
            }
          },
          async checkBot(id) { await this.api(`/bots/${id}/check`, { method: "POST" }); await this.refreshAll(); },
          openBotModal() {
            this.lastError = "";
            this.botModalOpen = true;
          },
          closeBotModal() {
            this.botModalOpen = false;
            this.lastError = "";
          },
          resetDestinationForm() { this.forms.destination = { bot_id: null, kind: "channel", chat_id: "", message_thread_id: null, alias: "", title: "" }; },
          openDestinationModal() { this.destinationModalOpen = true; },
          closeDestinationModal() { this.destinationModalOpen = false; },
          async createDestination() {
            await this.api("/destinations", { method: "POST", body: JSON.stringify(this.forms.destination) });
            this.closeDestinationModal();
            this.resetDestinationForm();
            await this.refreshAll();
          },
          async deleteDestination(id) {
            if (!confirm("Удалить адресата? История отправок останется без изменений.")) return;
            await this.api(`/destinations/${id}`, { method: "DELETE" });
            const nextHealth = { ...this.destinationHealth };
            delete nextHealth[id];
            this.destinationHealth = nextHealth;
            await this.refreshAll();
          },
          async checkDestination(id) {
            await this.api(`/destinations/${id}/check`, { method: "POST" });
            this.destinationHealth = { ...this.destinationHealth, [id]: await this.api(`/destinations/${id}/health`) };
            await this.refreshAll();
          },
          async createTemplate() { await this.api("/templates", { method: "POST", body: JSON.stringify(this.forms.template) }); this.forms.template = { tag: "", title: "", text: "", parse_mode: null, disable_web_page_preview: false }; this.templateValidation.result = null; this.templateSubTab = "saved"; await this.refreshAll(); },
          async loadTemplateVersions(template_id) {
            this.selectedTemplateId = template_id;
            this.templateVersions = await this.api(`/templates/${template_id}/versions`);
          },
          async rollbackTemplate(version) {
            await this.api(`/templates/${version.template_id}/rollback/${version.id}`, { method: "POST" });
            await this.loadTemplateVersions(version.template_id);
            await this.refreshAll();
          },
          async validateTemplate() {
            let variables = {};
            try {
              const rawVariables = this.templateValidation.variablesJson.trim();
              variables = rawVariables ? JSON.parse(rawVariables) : {};
              if (!variables || Array.isArray(variables) || typeof variables !== "object") {
                throw new Error("Проверочные переменные должны быть JSON-объектом");
              }
            } catch (error) {
              this.templateValidation.result = {
                ok: false,
                variables: [],
                missing_variables: [],
                rendered_text: null,
                error_message: error instanceof Error ? error.message : "JSON переменных не читается",
              };
              return;
            }
            this.templateValidation.result = await this.api("/templates/validate", {
              method: "POST",
              body: JSON.stringify({ text: this.forms.template.text, variables }),
            });
          },
          async sendText() { await this.api("/send/text", { method: "POST", body: JSON.stringify(this.forms.send) }); await this.refreshAll(); },
          async sendTemplate() { await this.api("/send/template", { method: "POST", body: JSON.stringify(this.forms.templateSend) }); await this.refreshAll(); },
          ensureFileSendAvailable() {
            if (this.fileSendAvailable) return true;
            this.lastError = `Отправка файлов отключена: ${this.fileSendUnavailableReason}`;
            return false;
          },
          async sendFile() {
            if (!this.ensureFileSendAvailable()) return;
            await this.api("/send/file", { method: "POST", body: JSON.stringify(this.forms.file) });
            await this.refreshAll();
          },
          currentSendPayload() {
            if (this.sendSubTab === "template") {
              return this.normalizeSendPayload({ kind: "template", ...this.forms.templateSend }, "template");
            }
            if (this.sendSubTab === "file") {
              return this.normalizeSendPayload({ kind: "file", ...this.forms.file }, "file");
            }
            return this.normalizeSendPayload({ kind: "text", ...this.forms.send }, "text");
          },
          normalizeSendPayload(payload, sendKind) {
            const targetMode = this.sendTargetMode[sendKind] || "chat_id";
            const normalized = { ...payload };
            if (targetMode === "destination") {
              normalized.destination_alias = "";
              normalized.chat_id = "";
            } else if (targetMode === "alias") {
              normalized.destination_id = null;
              normalized.chat_id = "";
            } else {
              normalized.destination_id = null;
              normalized.destination_alias = "";
            }
            if (normalized.send_mode !== "queued") {
              normalized.send_at = "";
            }
            return normalized;
          },
          targetModeFromPayload(payload) {
            if (payload.destination_id) return "destination";
            if (payload.destination_alias) return "alias";
            return "chat_id";
          },
          currentProfilePayload() {
            const payload = this.currentSendPayload();
            const sendKind = payload.kind;
            const base = {
              name: this.forms.profile.name || `Профиль ${new Date().toLocaleString("ru-RU")}`,
              bot_id: payload.bot_id,
              send_kind: sendKind,
              destination_id: payload.destination_id,
              destination_alias: payload.destination_alias,
              chat_id: payload.chat_id,
              message_thread_id: payload.message_thread_id,
              parse_mode: payload.parse_mode,
              variables: payload.variables || {},
              is_active: true,
            };
            if (sendKind === "template") {
              return { ...base, template_tag: payload.tag, media_type: "none" };
            }
            if (sendKind === "file") {
              return { ...base, media_type: payload.media_type, file_relative_path: payload.file_relative_path, caption: payload.caption };
            }
            return { ...base, text: payload.text, template_tag: payload.tag, media_type: "none", disable_web_page_preview: payload.disable_web_page_preview };
          },
          async createSendProfile() {
            if (this.sendSubTab === "file" && !this.ensureFileSendAvailable()) return;
            await this.api("/send-profiles", { method: "POST", body: JSON.stringify(this.currentProfilePayload()) });
            this.forms.profile.name = "";
            await this.refreshAll();
          },
          applySendProfile() {
            const profile = this.sendProfiles.find((item) => item.id === this.selectedSendProfileId);
            if (!profile) return;
            if (profile.send_kind === "template") {
              this.sendSubTab = "template";
              this.sendWorkTab = "quick";
              this.sendTargetMode.template = this.targetModeFromPayload(profile);
              Object.assign(this.forms.templateSend, {
                bot_id: profile.bot_id,
                destination_id: profile.destination_id,
                destination_alias: profile.destination_alias || "",
                chat_id: profile.chat_id || "",
                tag: profile.template_tag || "",
              });
              return;
            }
            if (profile.send_kind === "file") {
              if (!this.ensureFileSendAvailable()) return;
              this.sendSubTab = "file";
              this.sendWorkTab = "file";
              this.sendTargetMode.file = this.targetModeFromPayload(profile);
              Object.assign(this.forms.file, {
                bot_id: profile.bot_id,
                destination_id: profile.destination_id,
                destination_alias: profile.destination_alias || "",
                chat_id: profile.chat_id || "",
                media_type: profile.media_type === "document" ? "document" : "video",
                file_relative_path: profile.file_relative_path || "",
                caption: profile.caption || "",
                parse_mode: profile.parse_mode,
              });
              return;
            }
            this.sendSubTab = "text";
            this.sendWorkTab = "quick";
            this.sendTargetMode.text = this.targetModeFromPayload(profile);
            Object.assign(this.forms.send, {
              bot_id: profile.bot_id,
              destination_id: profile.destination_id,
              destination_alias: profile.destination_alias || "",
              chat_id: profile.chat_id || "",
              tag: profile.template_tag || "",
              text: profile.text || "",
              parse_mode: profile.parse_mode,
              disable_web_page_preview: profile.disable_web_page_preview,
            });
          },
          async previewCurrentSend() {
            if (this.sendSubTab === "file" && !this.ensureFileSendAvailable()) return;
            const payload = this.currentSendPayload();
            delete payload.send_mode;
            this.sendDryRun = await this.api("/send/preview", { method: "POST", body: JSON.stringify(payload) });
            this.sendWorkTab = "preview";
          },
          async preflightCurrentSend() {
            if (this.sendSubTab === "file" && !this.ensureFileSendAvailable()) return;
            const payload = this.currentSendPayload();
            delete payload.send_mode;
            this.sendDryRun = await this.api("/send/preflight", { method: "POST", body: JSON.stringify(payload) });
            this.sendWorkTab = "preview";
          },
          async createSendBatch() {
            if (this.sendSubTab === "file" && !this.ensureFileSendAvailable()) return;
            const payload = this.currentSendPayload();
            const body = {
              ...payload,
              name: this.forms.batch.name || `Batch ${new Date().toLocaleString("ru-RU")}`,
              send_kind: payload.kind,
              template_tag: payload.kind === "template" ? payload.tag : null,
              destination_ids: this.forms.batch.destination_ids,
              chat_ids: [],
            };
            delete body.kind;
            delete body.send_mode;
            delete body.destination_id;
            delete body.destination_alias;
            delete body.chat_id;
            delete body.tag;
            await this.api("/send-batches", { method: "POST", body: JSON.stringify(body) });
            this.forms.batch = { name: "", destination_ids: [] };
            await this.refreshAll();
          },
          async previewSendBatch(batch_id) {
            this.sendDryRun = await this.api(`/send-batches/${batch_id}/preview`, { method: "POST" });
          },
          async enqueueSendBatch(batch_id) {
            await this.api(`/send-batches/${batch_id}/enqueue`, { method: "POST" });
            await this.refreshAll();
          },
          async cancelSendBatch(batch_id) {
            await this.api(`/send-batches/${batch_id}/cancel`, { method: "POST" });
            await this.refreshAll();
          },
          async dryRunText() { this.sendDryRun = await this.api("/send/text/dry-run", { method: "POST", body: JSON.stringify(this.forms.send) }); },
          async dryRunTemplate() { this.sendDryRun = await this.api("/send/template/dry-run", { method: "POST", body: JSON.stringify(this.forms.templateSend) }); },
          async dryRunFile() {
            if (!this.ensureFileSendAvailable()) return;
            this.sendDryRun = await this.api("/send/file/dry-run", { method: "POST", body: JSON.stringify(this.forms.file) });
          },
          async loadMedia() {
            if (!this.ensureFileSendAvailable()) return;
            const params = new URLSearchParams({ path: this.mediaPath || "" });
            const listing = await this.api(`/media?${params.toString()}`);
            this.mediaPath = listing.relative_path;
            this.mediaItems = listing.items;
          },
          selectMediaFile(item) {
            if (item.kind !== "file") return;
            this.forms.file.file_relative_path = item.relative_path;
            if (item.media_type === "video" || item.media_type === "document") {
              this.forms.file.media_type = item.media_type;
            }
          },
          copyCurl(kind) {
            const path = {
              file: "/api/v1/send/file",
              template: "/api/v1/send/template",
              text: "/api/v1/send/text",
            }[kind];
            const payload = {
              file: this.forms.file,
              template: this.forms.templateSend,
              text: this.forms.send,
            }[kind];
            const token = this.apiToken ? ` -H "X-API-Token: ${this.apiToken}"` : "";
            const command = `curl -X POST ${location.origin}${path} -H "Content-Type: application/json"${token} -d '${JSON.stringify(payload)}'`;
            navigator.clipboard?.writeText(command);
          },
          copyMcpConnection() {
            navigator.clipboard?.writeText(JSON.stringify(this.mcpConnectionInfo, null, 2));
          },
          async startLogin() {
            const status = await this.api("/mtproto/login/start", { method: "POST", body: JSON.stringify({ phone: this.forms.mtproto.phone }) });
            this.mtprotoStatus = status;
            this.syncMtprotoStepFromStatus(status);
          },
          async confirmCode() {
            const status = await this.api("/mtproto/login/confirm-code", { method: "POST", body: JSON.stringify({ phone: this.forms.mtproto.phone, code: this.forms.mtproto.code }) });
            this.mtprotoStatus = status;
            this.syncMtprotoStepFromStatus(status);
          },
          async confirmPassword() {
            const status = await this.api("/mtproto/login/confirm-password", { method: "POST", body: JSON.stringify({ password: this.forms.mtproto.password }) });
            this.mtprotoStatus = status;
            this.syncMtprotoStepFromStatus(status);
          },
          openAnalyticsModal() { this.analyticsModalOpen = true; },
          closeAnalyticsModal() { this.analyticsModalOpen = false; },
          async createAnalyticsTarget() { await this.api("/analytics/targets", { method: "POST", body: JSON.stringify(this.forms.analytics) }); this.forms.analytics = { peer_ref: "", title: "" }; this.closeAnalyticsModal(); await this.refreshAll(); },
          async refreshAnalytics(target_id) { await this.api("/analytics/refresh", { method: "POST", body: JSON.stringify({ target_id }) }); await this.refreshAll(); },
          async retrySendHistory(send_history_id) { await this.api(`/send-history/${send_history_id}/retry`, { method: "POST" }); await this.refreshAll(); },
          async cancelSendHistory(send_history_id) { await this.api(`/send-history/${send_history_id}/cancel`, { method: "POST" }); await this.refreshAll(); },
          async saveDiagnosticSettings() { await this.api("/diagnostics/bot", { method: "PATCH", body: JSON.stringify({ bot_id: this.diagnosticSettings.bot_id, is_enabled: this.diagnosticSettings.is_enabled }) }); await this.refreshAll(); },
          async createDestinationFromDiagnosticUpdate(update_id) {
            await this.api(`/diagnostics/updates/${update_id}/destination`, {
              method: "POST",
              body: JSON.stringify(this.forms.diagnosticDestination),
            });
            await this.refreshAll();
          },
          async saveDiscoverySettings(bot_id, is_enabled) { await this.api(`/discovery/bots/${bot_id}`, { method: "PATCH", body: JSON.stringify({ is_enabled }) }); await this.refreshAll(); },
          discoveryFor(bot_id) { return this.discoverySettings.find((item) => item.bot_id === bot_id); },
          discoveryEnabled(bot_id) { return Boolean(this.discoveryFor(bot_id)?.is_enabled); },
          async runOpsScan() {
            this.opsLastScan = await this.api("/ops/scan", { method: "POST" });
            await this.refreshOps();
          },
          async previewOpsAction(recommendation_id) {
            this.selectedOpsRecommendation = recommendation_id;
            this.opsPreview = await this.api(`/ops/recommendations/${recommendation_id}/preview`, { method: "POST" });
            await this.refreshOps();
          },
          async applyOpsAction(recommendation_id) {
            await this.api(`/ops/recommendations/${recommendation_id}/apply`, { method: "POST" });
            this.opsPreview = null;
            this.selectedOpsRecommendation = null;
            await this.refreshOps();
            await this.refreshAll();
          },
          async dismissOpsRecommendation(recommendation_id) {
            await this.api(`/ops/recommendations/${recommendation_id}/dismiss`, { method: "POST" });
            if (this.selectedOpsRecommendation === recommendation_id) {
              this.opsPreview = null;
              this.selectedOpsRecommendation = null;
            }
            await this.refreshOps();
          },
          async updateOpsRule(rule, patch) {
            try {
              const updated = await this.api(`/ops/rules/${rule.id}`, {
                method: "PATCH",
                body: JSON.stringify(patch),
              });
              const index = this.opsRules.findIndex((item) => item.id === rule.id);
              if (index >= 0) this.opsRules.splice(index, 1, updated);
            } catch (error) {
              const message = error.message;
              await this.refreshOps().catch(() => {});
              this.lastError = message;
              throw error;
            }
          },
          async runOpsRule(rule_id) {
            await this.api(`/ops/rules/${rule_id}/run`, { method: "POST" });
            await this.refreshOps();
          },
          async pauseOpsRule(rule_id) {
            await this.api(`/ops/rules/${rule_id}/pause`, { method: "POST" });
            await this.refreshOps();
          },
          async resumeOpsRule(rule_id) {
            await this.api(`/ops/rules/${rule_id}/resume`, { method: "POST" });
            await this.refreshOps();
          },
          setMcpPreset(preset) {
            const allowed = {
              read: ["list_bots", "list_destinations", "list_message_templates", "get_analytics_summary", "get_send_history"],
              sender: ["list_bots", "list_destinations", "list_message_templates", "get_analytics_summary", "get_send_history", "send_text", "send_template", "send_file_from_shared_path"],
              full: this.mcpSettings.tools.map((tool) => tool.name),
            }[preset];
            this.mcpSettings.tools.forEach((tool) => { tool.enabled = allowed.includes(tool.name); });
          },
          async saveMcpSettings() {
            await this.api("/mcp/settings", {
              method: "PATCH",
              body: JSON.stringify({
                is_enabled: this.mcpSettings.is_enabled,
                allow_legacy_sse: this.mcpSettings.allow_legacy_sse,
                enabled_tools: this.mcpSettings.tools.filter((tool) => tool.enabled).map((tool) => tool.name),
              }),
            });
            await this.refreshAll();
          },
          openApiTokenModal() { this.apiTokenModalOpen = true; },
          closeApiTokenModal() { this.apiTokenModalOpen = false; this.createdApiToken = ""; },
          openRevokeTokenModal(token) { this.revokeTokenTarget = token; this.revokeTokenModalOpen = true; },
          closeRevokeTokenModal() { this.revokeTokenTarget = null; this.revokeTokenModalOpen = false; },
          async createApiToken() {
            const created = await this.api("/auth/tokens", { method: "POST", body: JSON.stringify(this.forms.apiToken) });
            this.createdApiToken = created.token;
            this.apiToken = created.token;
            localStorage.setItem("tgApiToken", created.token);
            await this.establishApiSession();
            await this.refreshAll();
          },
          async revokeApiToken(token_id) {
            await this.api(`/auth/tokens/${token_id}`, { method: "DELETE" });
            await this.refreshAll();
          },
          async confirmRevokeApiToken() {
            if (!this.revokeTokenTarget || this.tokenRevocationBusy) return;
            this.tokenRevocationBusy = true;
            const tokenWasCurrent = Boolean(
              this.apiToken
              && this.revokeTokenTarget?.token_prefix
              && this.apiToken.startsWith(this.revokeTokenTarget.token_prefix),
            );
            try {
              await this.revokeApiToken(this.revokeTokenTarget.id);
              if (tokenWasCurrent) {
                this.apiToken = "";
                localStorage.removeItem("tgApiToken");
              }
              this.lastError = "";
            } catch (error) {
              const message = error instanceof Error ? error.message : "Ошибка отзыва токена";
              this.lastError = message;
            } finally {
              this.tokenRevocationBusy = false;
              this.closeRevokeTokenModal();
            }
          },
          normalizedOperationsSettings() {
            const payload = { ...this.operationsSettings };
            payload.cors_allowed_origins = this.parseCsv(this.operationsText.cors_allowed_origins);
            payload.mcp_allowed_origins = this.parseCsv(this.operationsText.mcp_allowed_origins);
            payload.protected_api_hosts = this.parseCsv(this.operationsText.protected_api_hosts);
            [
              "rate_limit_per_minute",
              "quiet_hours_start",
              "quiet_hours_end",
              "callback_url",
              "backup_git_repo_url",
              "backup_git_api_base_url",
              "backup_git_api_token",
            ].forEach((key) => {
              if (payload[key] === "") payload[key] = null;
            });
            payload.quiet_hours_start = this.formatQuietHoursValue(payload.quiet_hours_start);
            payload.quiet_hours_end = this.formatQuietHoursValue(payload.quiet_hours_end);
            if (payload.backup_git_auth_method === "none") payload.backup_git_api_token = null;
            if (!payload.callback_enabled) payload.callback_url = payload.callback_url || null;
            if (!payload.backup_schedule_enabled) payload.backup_schedule_push_to_git = false;
            if (!payload.backup_git_service) payload.backup_git_service = "auto";
            if (!payload.backup_git_auth_method) payload.backup_git_auth_method = "token";
            return payload;
          },
          setTelegramBotApiPreset(url) {
            this.operationsSettings.telegram_bot_api_base_url = url;
          },
          isCloudBotApiUrl(url) {
            return String(url || "").includes("api.telegram.org");
          },
          isLocalBotApiUrl(url) {
            const value = String(url || "");
            return Boolean(value) && !this.isCloudBotApiUrl(value);
          },
          applyMaxLocalFilePreset(value) {
            this.operationsSettings.max_local_file_bytes = value;
          },
          formatQuietHoursValue(value, finalize = false) {
            const digits = String(value || "").replace(/\D/g, "").slice(0, 4);
            if (!digits) return null;
            if (digits.length <= 2) {
              if (!finalize) return digits;
              const hours = Math.min(23, Number(digits || "0"));
              return `${String(hours).padStart(2, "0")}:00`;
            }
            const hours = Math.min(23, Number(digits.slice(0, 2) || "0"));
            const minutes = Math.min(59, Number(digits.slice(2, 4) || "0"));
            return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
          },
          formatQuietHoursInput(field, finalize = false) {
            this.operationsSettings[field] = this.formatQuietHoursValue(this.operationsSettings[field], finalize) || "";
          },
          inferBackupGitService(repoUrl) {
            const value = String(repoUrl || "").toLowerCase();
            if (value.includes("github.com")) return "github";
            if (value.includes("gitea") || value.includes("/api/v1") || value.includes("/repos/")) return "gitea";
            return "auto";
          },
          applyBackupServiceDefaults() {
            const service = this.operationsSettings.backup_git_service || "auto";
            if (service === "auto" && this.operationsSettings.backup_git_repo_url) {
              this.operationsSettings.backup_git_service = this.inferBackupGitService(this.operationsSettings.backup_git_repo_url);
              return this.applyBackupServiceDefaults();
            }
            if (service === "github") {
              if (
                !this.operationsSettings.backup_git_api_base_url
                || this.operationsSettings.backup_git_api_base_url.includes("api.github.com")
              ) {
                this.operationsSettings.backup_git_api_base_url = "https://api.github.com";
              }
              return;
            }
            if (service === "gitea" && !this.operationsSettings.backup_git_api_base_url) {
              this.operationsSettings.backup_git_api_base_url = "https://gitea.example/api/v1";
            }
          },
          async saveRuntimeSettings() {
            this.operationsSettings = await this.api("/operations/settings", {
              method: "PATCH",
              body: JSON.stringify(this.normalizedOperationsSettings()),
            });
            await this.refreshAll();
          },
          async saveTelegramEgressSettings() {
            this.telegramEgressState = await this.api("/operations/telegram-egress", {
              method: "PATCH",
              body: JSON.stringify(this.telegramEgressDraft),
            });
            this.syncTelegramEgressDraft();
          },
          async uploadTelegramEgressConfig() {
            this.telegramEgressState = await this.api("/operations/telegram-egress/config", {
              method: "POST",
              body: JSON.stringify({
                provider: this.telegramEgressConfig.provider,
                profile_text: this.telegramEgressConfig.profile_text,
                auth_text: this.telegramEgressConfig.provider === "openvpn"
                  ? this.telegramEgressConfig.auth_text
                  : null,
              }),
            });
            this.syncTelegramEgressDraft();
          },
          async checkTelegramEgress() {
            this.telegramEgressStatus = await this.api("/operations/telegram-egress/check", {
              method: "POST",
            });
            this.telegramEgressState = await this.api("/operations/telegram-egress");
            this.syncTelegramEgressDraft();
          },
          async connectTelegramEgress() {
            this.telegramEgressStatus = await this.api("/operations/telegram-egress/connect", {
              method: "POST",
            });
            this.telegramEgressState = await this.api("/operations/telegram-egress");
            this.syncTelegramEgressDraft();
          },
          async disconnectTelegramEgress() {
            this.telegramEgressStatus = await this.api("/operations/telegram-egress/disconnect", {
              method: "POST",
            });
            this.telegramEgressState = await this.api("/operations/telegram-egress");
            this.syncTelegramEgressDraft();
          },
          async restartTelegramEgress() {
            this.telegramEgressStatus = await this.api("/operations/telegram-egress/restart", {
              method: "POST",
            });
            this.telegramEgressState = await this.api("/operations/telegram-egress");
            this.syncTelegramEgressDraft();
          },
          async checkBackupRepository() {
            this.operationsSettings = await this.api("/operations/settings", {
              method: "PATCH",
              body: JSON.stringify(this.normalizedOperationsSettings()),
            });
            this.backupRepoCheck = await this.api("/operations/backup/check-repo", {
              method: "POST",
              body: JSON.stringify({}),
            });
            this.syncOperationsText();
          },
          async runBackupPreflight() {
            this.operationsSettings = await this.api("/operations/settings", {
              method: "PATCH",
              body: JSON.stringify(this.normalizedOperationsSettings()),
            });
            this.backupPreflight = await this.api("/operations/backup/preflight", {
              method: "POST",
              body: JSON.stringify({
                include_secrets: this.operationsSettings.backup_include_secrets,
                push_to_git: false,
              }),
            });
            this.backupDiff = this.backupPreflight.diff;
            await this.refreshAll();
          },
          async loadBackupDiff() {
            this.backupDiff = await this.api("/operations/backup/diff", {
              method: "POST",
              body: JSON.stringify({}),
            });
          },
          parseBackupImportJson() {
            const raw = this.backupImport.jsonText.trim();
            if (!raw) throw new Error("Вставь backup JSON");
            return JSON.parse(raw);
          },
          ensureRestoreWizardReady() {
            if (!this.restoreWizard.runId) {
              this.lastError = "Выбери backup run для restore";
              return false;
            }
            if (!this.restoreWizard.sections.length) {
              this.lastError = "Выбери хотя бы одну секцию для restore";
              return false;
            }
            return true;
          },
          async previewBackupRunRestore() {
            if (!this.ensureRestoreWizardReady()) return;
            try {
              this.restoreWizard.preview = await this.api(`/operations/backup/runs/${this.restoreWizard.runId}/restore-preview`, {
                method: "POST",
                body: JSON.stringify({ sections: this.restoreWizard.sections }),
              });
              this.backupDiff = this.restoreWizard.preview.diff;
            } catch (error) {
              this.lastError = error instanceof Error ? error.message : "Restore preview не выполнен";
            }
          },
          async applyBackupRunRestore() {
            if (!this.ensureRestoreWizardReady()) return;
            try {
              this.restoreWizard.lastApply = await this.api(`/operations/backup/runs/${this.restoreWizard.runId}/restore`, {
                method: "POST",
                body: JSON.stringify({ sections: this.restoreWizard.sections, confirm: this.restoreWizard.confirm }),
              });
              this.restoreWizard.confirm = "";
              await this.refreshAll();
            } catch (error) {
              this.lastError = error instanceof Error ? error.message : "Restore не выполнен";
            }
          },
          async previewBackupImport() {
            try {
              const snapshot = this.parseBackupImportJson();
              this.backupImport.preview = await this.api("/operations/backup/import/preview", {
                method: "POST",
                body: JSON.stringify({ snapshot }),
              });
              this.backupDiff = this.backupImport.preview.diff;
            } catch (error) {
              this.lastError = error instanceof Error ? error.message : "Backup JSON не читается";
            }
          },
          async applyBackupImport() {
            try {
              const snapshot = this.parseBackupImportJson();
              this.backupImport.lastApply = await this.api("/operations/backup/import/apply", {
                method: "POST",
                body: JSON.stringify({ snapshot, confirm: this.backupImport.confirm }),
              });
              this.backupImport.confirm = "";
              await this.refreshAll();
            } catch (error) {
              this.lastError = error instanceof Error ? error.message : "Restore не выполнен";
            }
          },
          async runBackup(push_to_git) {
            const run = await this.api("/operations/backup/run", {
              method: "POST",
              body: JSON.stringify({
                include_secrets: this.operationsSettings.backup_include_secrets,
                push_to_git,
              }),
            });
            this.backupRuns = [run, ...this.backupRuns.filter((item) => item.id !== run.id)];
          },
        },
      }).mount("#app");
