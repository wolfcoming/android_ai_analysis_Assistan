/* 安卓开发助手 - 前端主文件 (Vue 3 + Chart.js) */

// ============================================================
// 1. TrendChart 组件
// ============================================================
var TrendChart = {
    name: 'TrendChart',
    template: '#tpl-trend-chart',
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
var ChatPanel = { template: '#tpl-chat-panel',
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
var InfoPanel = { template: '#tpl-info-panel',
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
