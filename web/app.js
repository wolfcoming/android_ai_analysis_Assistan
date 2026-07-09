/* 安卓开发助手 - 前端主文件 (Vue 3 + Chart.js) */

// ============================================================
// 1. TrendChart 组件
// ============================================================
var TrendChart = {
    name: 'TrendChart',
    template: '<div class="chart-container"><canvas :ref="chartId"></canvas></div>',
    props: {
        chartId: { type: String, required: true },
        label: { type: String, default: '' },
        color: { type: String, default: '#e94560' },
        dataKey: { type: String, required: true },
        unit: { type: String, default: '' },
        maxPoints: { type: Number, default: 150 },
    },
    data() {
        return { chart: null, dataPoints: [] };
    },
    mounted() {
        var ctx = this.$refs[this.chartId]?.getContext('2d');
        if (!ctx) return;
        this.chart = new Chart(ctx, {
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
                            callback: function(v) { return v + this.unit; },
                            maxTicksLimit: 4,
                        },
                        grid: { color: '#2a2a4a' },
                    },
                },
            },
        });
    },
    methods: {
        updateChart: function(dataList) {
            if (!this.chart || !dataList.length) return;
            var labels = dataList.map(function(_, i) { return i; });
            var values = dataList.map(function(d) { return d[this.dataKey] || 0; }, this);
            this.chart.data.labels = labels;
            this.chart.data.datasets[0].data = values;
            this.chart.update('none');
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
                <div class="bubble" v-html="renderMarkdown(msg.content)"></div>
                <div v-if="msg.tools && msg.tools.length" class="tools-info">
                    {{ msg.tools.map(function(t){return t.tool}).join(', ') }}
                </div>
            </div>
            <div v-if="loading" class="loading">正在分析...</div>
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
            chatHistory: [],
        };
    },
    methods: {
        sendMessage: async function() {
            var text = this.input.trim();
            if (!text || this.loading) return;

            this.messages.push({ role: 'user', content: text, tools: [] });
            this.input = '';
            this.loading = true;
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
                var data = await res.json();
                var tools = data.intermediate_steps || [];

                this.messages.push({
                    role: 'agent',
                    content: data.output || '抱歉，没有获取到回复。',
                    tools: tools,
                });

                this.chatHistory.push(['human', text]);
                this.chatHistory.push(['ai', data.output || '']);
                if (this.chatHistory.length > 20) {
                    this.chatHistory = this.chatHistory.slice(-20);
                }
            } catch (err) {
                this.messages.push({
                    role: 'agent',
                    content: '请求失败: ' + err.message,
                    tools: [],
                });
            } finally {
                this.loading = false;
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
                <span class="metric-badge">PSS: <span class="val">{{ fmtMem(metrics.pss_total) }}MB</span></span>
                <span class="metric-badge">Java Heap: <span class="val">{{ fmtMem(metrics.java_heap) }}MB</span></span>
                <span class="metric-badge">Native Heap: <span class="val">{{ fmtMem(metrics.native_heap) }}MB</span></span>
                <span class="metric-badge">CPU: <span class="val">{{ metrics.cpu_percent }}%</span></span>
                <span class="metric-badge">FPS: <span class="val">{{ metrics.estimated_fps }}</span></span>
                <span class="metric-badge">掉帧: <span class="val">{{ metrics.janky_count }}/{{ metrics.frame_count }}</span></span>
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
                <button disabled title="待完善">一键内存诊断</button>
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
