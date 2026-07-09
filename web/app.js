/* 安卓开发助手 - 前端主文件 (Vue 3 + Chart.js) */

// ============================================================
// 1. TrendChart 组件
// ============================================================
var TrendChart = {
    name: 'TrendChart',
    template: '<div class="chart-container"><div class="chart-legend">{{ label }}</div><canvas ref="chartCanvas"></canvas></div>',
    props: {
        chartId: { type: String, required: true },
        label: { type: String, default: '' },
        color: { type: String, default: '#e94560' },
        dataKey: { type: String, required: true },
        unit: { type: String, default: '' },
        maxPoints: { type: Number, default: 150 },
    },
    data: function() {
        return { _unit: '', _isMemory: false };
    },
    mounted: function() {
        var self = this;
        this._unit = this.unit;
        this._isMemory = (this.dataKey === 'pss_total' || this.dataKey === 'java_heap' || this.dataKey === 'native_heap');
        var canvas = this.$refs.chartCanvas;
        if (!canvas) return;
        var ctx = canvas.getContext('2d');
        this._chart = Vue.markRaw(new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: this.label,
                    data: [],
                    borderColor: this.color,
                    backgroundColor: this.color + '20',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 1.5,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: {
                        display: true,
                        ticks: {
                            color: '#888',
                            font: { size: 10 },
                            callback: function(v) { return v.toFixed(1) + self._unit; },
                            maxTicksLimit: 4,
                        },
                        grid: { color: '#2a2a4a' },
                    },
                },
            },
        }));
    },
    methods: {
        updateChart: function(dataList) {
            if (!this._chart || !dataList || !dataList.length) return;
            var dk = this.dataKey;
            var isMem = this._isMemory;
            var labels = [];
            var values = [];
            for (var i = 0; i < dataList.length; i++) {
                labels.push(i);
                var v = dataList[i][dk] || 0;
                values.push(isMem ? +(v / 1024).toFixed(1) : v);
            }
            this._chart.data.labels = labels;
            this._chart.data.datasets[0].data = values;
            this._chart.update('none');
        },
    },
};

// ============================================================
// 2. ChatPanel 组件
// ============================================================
var ChatPanel = {
    template: `
    <div class="chat-panel">
        <div class="chat-header">安卓开发助手</div>
        <div class="chat-messages" ref="msgContainer">
            <div v-if="messages.length === 0" class="msg agent">
                <div class="bubble">
                    <p>你好！我是安卓开发助手，可以帮你：</p>
                    <ul>
                        <li>查看设备配置和应用信息</li>
                        <li>分析内存占用和卡顿原因</li>
                        <li>排查崩溃和 ANR 问题</li>
                    </ul>
                    <p>请先确认手机已通过 USB 连接并开启调试模式。</p>
                </div>
            </div>
            <div v-for="(msg, idx) in messages" :key="idx" :class="'msg ' + msg.role">
                <div v-if="msg.thinking && msg.thinking.length" class="thinking-history">
                    <div v-for="(th, ti) in msg.thinking" :key="ti" class="th-block">
                        <span class="th-label">{{ th.label }}</span>
                        <span class="th-text">{{ th.content }}</span>
                    </div>
                </div>
                <div class="bubble" v-html="renderMarkdown(msg.content)"></div>
                <div v-if="msg.tools && msg.tools.length" class="tools-info">
                    <div v-for="(t, i) in msg.tools" :key="i" class="tool-line">
                        <span class="tool-done">✅ {{ t.name }}</span>
                    </div>
                </div>
            </div>
            <div v-if="loading" class="thinking-box">
                <div class="thinking-status">{{ thinkingStatus }}</div>
                <div v-for="(th, i) in thinkingSteps" :key="'th'+i" class="th-live">
                    <span class="th-live-icon">💭</span>
                    <span class="th-live-text">{{ th.content }}</span>
                </div>
                <div v-for="(t, i) in runningTools" :key="'rt'+i" class="tool-line">
                    <span v-if="t.status === 'running'" class="tool-running">⏳ {{ t.name }}: {{ t.detail }}</span>
                    <span v-else class="tool-done">✅ {{ t.name }}: {{ t.detail }}</span>
                </div>
            </div>
        </div>
        <div class="chat-input-area">
            <input
                v-model="input"
                @keyup.enter="sendMessage"
                placeholder="输入你的问题，如：当前连接了什么手机？微信占了多少内存？"
                :disabled="loading"
            />
            <button @click="sendMessage" :disabled="loading || !input.trim()">发送</button>
        </div>
    </div>
    `,
    data: function() {
        return {
            input: '',
            messages: [],
            loading: false,
            thinkingStatus: '',
            thinkingSteps: [],
            runningTools: [],
            chatHistory: [],
        };
    },
    mounted: function() {
        var self = this;
        window.addEventListener('agent-quick-action', function(e) {
            if (e.detail && e.detail.message) {
                self.input = e.detail.message;
                self.sendMessage();
            }
        });
    },
    methods: {
        sendMessage: async function() {
            var text = this.input.trim();
            if (!text || this.loading) return;

            this.messages.push({ role: 'user', content: text, tools: [], thinking: [] });
            this.input = '';
            this.loading = true;
            this.thinkingStatus = '正在分析...';
            this.thinkingSteps = [];
            this.runningTools = [];
            var savedThinking = [];
            var savedTools = [];
            var self = this;
            this.$nextTick(function() { self.scrollToBottom(); });

            try {
                var res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: text,
                        chat_history: this.chatHistory,
                    }),
                });

                // 流式读取 SSE 响应
                var reader = res.body.getReader();
                var decoder = new TextDecoder();
                var buffer = '';
                var toolList = [];
                var finalOutput = '';

                while (true) {
                    var result = await reader.read();
                    if (result.done) break;

                    buffer += decoder.decode(result.value, { stream: true });
                    var lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i].trim();
                        if (!line.startsWith('data: ')) continue;

                        var jsonStr = line.substring(6);
                        try {
                            var event = JSON.parse(jsonStr);

                            if (event.type === 'thinking') {
                                var brief = event.content.length > 120
                                    ? event.content.substring(0, 120) + '...'
                                    : event.content;
                                this.thinkingSteps.push({ content: brief });
                                savedThinking.push({
                                    label: 'LLM 推理',
                                    content: event.content,
                                });
                                this.thinkingStatus = 'LLM 正在推理...';
                                this.$nextTick(function() { self.scrollToBottom(); });

                            } else if (event.type === 'tool_start') {
                                var toolEntry = {
                                    name: event.tool,
                                    detail: typeof event.input === 'string'
                                        ? event.input.substring(0, 100)
                                        : JSON.stringify(event.input).substring(0, 100),
                                    status: 'running',
                                };
                                this.runningTools.push(toolEntry);
                                this.thinkingStatus = '调用工具: ' + event.tool;
                                savedTools.push({ name: event.tool });
                                this.$nextTick(function() { self.scrollToBottom(); });

                            } else if (event.type === 'tool_end') {
                                for (var j = this.runningTools.length - 1; j >= 0; j--) {
                                    if (this.runningTools[j].status === 'running') {
                                        this.runningTools[j].status = 'done';
                                        this.runningTools[j].detail = event.output
                                            ? event.output.substring(0, 100)
                                            : '完成';
                                        break;
                                    }
                                }
                                this.thinkingStatus = '分析结果中...';
                                this.$nextTick(function() { self.scrollToBottom(); });

                            } else if (event.type === 'tool_error') {
                                for (var k = this.runningTools.length - 1; k >= 0; k--) {
                                    if (this.runningTools[k].status === 'running') {
                                        this.runningTools[k].status = 'done';
                                        this.runningTools[k].detail = '❌ ' + event.error.substring(0, 80);
                                        break;
                                    }
                                }
                            } else if (event.type === 'output') {
                                finalOutput = event.content;
                                this.thinkingStatus = '生成回复中...';
                            }
                        } catch (e) {
                            // 跳过非 JSON 行
                        }
                    }
                }

                // 流结束，添加最终回复
                this.messages.push({
                    role: 'agent',
                    content: finalOutput || '抱歉，没有获取到回复。',
                    tools: savedTools,
                    thinking: savedThinking,
                });

                this.chatHistory.push(['human', text]);
                this.chatHistory.push(['ai', finalOutput || '']);
                if (this.chatHistory.length > 20) {
                    this.chatHistory = this.chatHistory.slice(-20);
                }
            } catch (err) {
                this.messages.push({
                    role: 'agent',
                    content: '请求失败: ' + err.message,
                    tools: [],
                    thinking: [],
                });
            } finally {
                this.loading = false;
                this.thinkingStatus = '';
                this.thinkingSteps = [];
                this.runningTools = [];
                var self2 = this;
                this.$nextTick(function() { self2.scrollToBottom(); });
            }
        },
        renderMarkdown: function(text) {
            if (!text) return '';
            try {
                return marked.parse(text);
            } catch (e) {
                return text.replace(/\n/g, '<br>');
            }
        },
        scrollToBottom: function() {
            var el = this.$refs.msgContainer;
            if (el) el.scrollTop = el.scrollHeight;
        },
    },
};

// ============================================================
// 3. InfoPanel 组件
// ============================================================
var InfoPanel = {
    template: `
    <div class="info-panel" v-if="!deviceError">
        <div class="info-section">
            <h3>设备概览</h3>
            <div v-if="deviceInfo" class="info-grid">
                <div class="info-item"><span class="label">品牌:</span> <span class="value">{{ deviceInfo.brand }}</span></div>
                <div class="info-item"><span class="label">型号:</span> <span class="value">{{ deviceInfo.model }}</span></div>
                <div class="info-item"><span class="label">Android:</span> <span class="value">{{ deviceInfo.android_version }} (API {{ deviceInfo.api_level }})</span></div>
                <div class="info-item"><span class="label">CPU:</span> <span class="value">{{ deviceInfo.cpu_abi }} x {{ deviceInfo.cpu_cores }}核</span></div>
                <div class="info-item"><span class="label">分辨率:</span> <span class="value">{{ deviceInfo.screen_size }}</span></div>
                <div class="info-item"><span class="label">密度:</span> <span class="value">{{ deviceInfo.screen_density }}</span></div>
            </div>
            <div v-else class="no-device">正在加载设备信息...</div>
        </div>

        <div class="info-section">
            <h3>目标应用</h3>
            <div v-if="targetApp" class="info-item"><span class="value">{{ targetApp }}</span></div>
            <div v-else class="info-item"><span class="label">请在手机上打开目标应用</span></div>
            <input v-model="appInput" @keyup.enter="setApp" placeholder="输入包名，如 com.tencent.mm" style="margin-top:6px;padding:4px 8px;background:#0f3460;border:1px solid #2a2a4a;border-radius:4px;color:#e0e0e0;font-size:12px;width:200px;" />
            <button @click="setApp" style="margin-left:6px;padding:4px 10px;background:#e94560;border:none;border-radius:4px;color:#fff;font-size:12px;cursor:pointer;">确认</button>
        </div>

        <div class="info-section">
            <h3>实时性能 <span style="font-size:11px;color:#888;">(2s刷新)</span></h3>
            <div class="metric-row">
                <span class="metric-badge" title="Proportional Set Size — 应用实际占用的物理内存（含按比例分摊的共享库），是评估内存占用的核心指标。持续上涨可能表示内存泄漏。">PSS: <span class="val">{{ fmtMem(metrics.pss_total) }}MB</span></span>
                <span class="metric-badge" title="Java 虚拟机堆内存 — Dalvik/ART 为 Java/Kotlin 对象分配的内存。频繁 GC 或堆持续增长通常意味着对象分配过多或存在泄漏。">Java Heap: <span class="val">{{ fmtMem(metrics.java_heap) }}MB</span></span>
                <span class="metric-badge" title="Native 堆内存 — C/C++ 代码通过 malloc/new 分配的内存，如媒体编解码、游戏引擎、自定义 Native 库。泄漏时 GC 无法回收。">Native Heap: <span class="val">{{ fmtMem(metrics.native_heap) }}MB</span></span>
                <span class="metric-badge" title="CPU 使用率 — 应用所有进程的 CPU 占用百分比。持续高于 30% 需关注，可能由密集计算、死循环或错误的重绘逻辑导致。">CPU: <span class="val">{{ metrics.cpu_percent }}%</span></span>
                <span class="metric-badge" title="每秒渲染帧数 — 基于 dumpsys gfxinfo 统计。60fps 为流畅基准，低于 30fps 用户能明显感知卡顿。需在滑动/动画时观察。">FPS: <span class="val">{{ metrics.estimated_fps }}</span></span>
                <span class="metric-badge" title="掉帧数 / 总渲染帧数 — Janky frame 指渲染耗时超过 16.67ms 的帧（低于 60fps）。比率越高卡顿越严重。">掉帧: <span class="val">{{ metrics.janky_count }}/{{ metrics.frame_count }}</span></span>
            </div>
        </div>

        <div class="info-section">
            <h3>历史趋势 (5min)</h3>
            <trend-chart chart-id="chart-pss" label="PSS (MB)" color="#e94560" data-key="pss_total" unit="MB" ref="chartPss"></trend-chart>
            <trend-chart chart-id="chart-jheap" label="Java Heap (MB)" color="#f0a500" data-key="java_heap" unit="MB" ref="chartJheap"></trend-chart>
            <trend-chart chart-id="chart-nheap" label="Native Heap (MB)" color="#00b4d8" data-key="native_heap" unit="MB" ref="chartNheap"></trend-chart>
            <trend-chart chart-id="chart-fps" label="FPS" color="#2ecc71" data-key="estimated_fps" unit="" ref="chartFps"></trend-chart>
            <trend-chart chart-id="chart-cpu" label="CPU (%)" color="#9b59b6" data-key="cpu_percent" unit="%" ref="chartCpu"></trend-chart>
        </div>

        <div class="info-section">
            <h3>快捷操作</h3>
            <div class="quick-actions">
                <button disabled title="待完善">导出诊断报告</button>
                <button disabled title="待完善">切换设备</button>
                <button disabled title="待完善">保存对话历史</button>
                <button @click="quickMemoryDiagnosis" title="一键内存诊断">一键内存诊断</button>
                <button disabled title="待完善">一键卡顿诊断</button>
            </div>
        </div>
    </div>
    <div class="info-panel" v-else>
        <div class="no-device">
            <p>{{ deviceError }}</p>
            <p style="margin-top:10px;font-size:13px;color:#666;">
                请确认：<br>
                1. 手机已通过 USB 连接 Mac<br>
                2. 已开启开发者模式 & USB 调试<br>
                3. 已在手机上授权此电脑<br>
                4. 运行 adb devices 确认设备已连接
            </p>
        </div>
    </div>
    `,
    data: function() {
        return {
            deviceInfo: null,
            deviceError: '',
            targetApp: '',
            appInput: '',
            metrics: { pss_total: 0, java_heap: 0, native_heap: 0, cpu_percent: 0, estimated_fps: 0, janky_count: 0, frame_count: 0 },
            trendData: [],
            evtSource: null,
            refreshTimer: null,
        };
    },
    mounted: function() {
        this.loadDeviceInfo();
        this.startSSE();
    },
    beforeUnmount: function() {
        this.stopSSE();
        if (this.refreshTimer) clearInterval(this.refreshTimer);
    },
    methods: {
        loadDeviceInfo: async function() {
            try {
                var res = await fetch('/api/device/info');
                var data = await res.json();
                if (data.error) {
                    this.deviceError = data.error;
                } else if (data.connected) {
                    this.deviceInfo = data;
                    this.deviceError = '';
                } else {
                    this.deviceError = '未检测到已连接的 Android 设备';
                }
            } catch (err) {
                this.deviceError = '无法连接到后端服务，请确认服务已启动';
            }
        },
        setApp: function() {
            var val = this.appInput.trim();
            if (val) {
                this.targetApp = val;
                this.stopSSE();
                this.startSSE();
            }
        },
        startSSE: function() {
            this.stopSSE();
            var pkgParam = this.targetApp ? '?package_name=' + encodeURIComponent(this.targetApp) : '';
            this.evtSource = new EventSource('/api/stream' + pkgParam);
            var self = this;
            this.evtSource.onmessage = function(event) {
                try {
                    var data = JSON.parse(event.data);
                    if (data.error) return;
                    self.metrics = data;
                    self.trendData.push(data);
                    if (self.trendData.length > 150) {
                        self.trendData = self.trendData.slice(-150);
                    }
                    self.updateCharts();
                } catch (e) { /* ignore */ }
            };
            this.evtSource.onerror = function() {
                if (self.evtSource) self.evtSource.close();
                setTimeout(function() { self.startSSE(); }, 5000);
            };

            if (this.refreshTimer) clearInterval(this.refreshTimer);
            this.refreshTimer = setInterval(function() { self.updateCharts(); }, 2000);
        },
        stopSSE: function() {
            if (this.evtSource) {
                this.evtSource.close();
                this.evtSource = null;
            }
        },
        updateCharts: function() {
            if (this.trendData.length > 0) {
                var recent = this.trendData.slice(-150);
                var c = this.$refs;
                if (c && c.chartPss) c.chartPss.updateChart(recent);
                if (c && c.chartJheap) c.chartJheap.updateChart(recent);
                if (c && c.chartNheap) c.chartNheap.updateChart(recent);
                if (c && c.chartFps) c.chartFps.updateChart(recent);
                if (c && c.chartCpu) c.chartCpu.updateChart(recent);
            }
        },
        fmtMem: function(kb) {
            if (!kb) return '0.0';
            return (kb / 1024).toFixed(1);
        },
        quickMemoryDiagnosis: function() {
            if (!this.targetApp) {
                alert('请先在「目标应用」中输入包名（如 com.tencent.mm）并点击确认');
                return;
            }
            window.dispatchEvent(new CustomEvent('agent-quick-action', {
                detail: { message: '请对 ' + this.targetApp + ' 执行一键内存诊断（memory diagnosis），找出内存占用最大的类' }
            }));
        },
    },
};

// ============================================================
// 4. 初始化 Vue 应用
// ============================================================
var app = Vue.createApp({});
app.component('trend-chart', TrendChart);
app.component('chat-panel', ChatPanel);
app.component('info-panel', InfoPanel);
app.mount('#app');
