var InfoPanel = {
    template: `
    <div class="info-panel" v-if="!deviceError">
        <!-- 设备概览 -->
        <div class="info-section">
            <h3>📱 设备概览</h3>
            <div v-if="deviceInfo" class="info-grid">
                <div class="info-item"><span class="label">品牌:</span> <span class="value">{{ deviceInfo.brand }}</span></div>
                <div class="info-item"><span class="label">型号:</span> <span class="value">{{ deviceInfo.model }}</span></div>
                <div class="info-item"><span class="label">Android:</span> <span class="value">{{ deviceInfo.android_version }} (API {{ deviceInfo.api_level }})</span></div>
                <div class="info-item"><span class="label">CPU:</span> <span class="value">{{ deviceInfo.cpu_abi }} × {{ deviceInfo.cpu_cores }}核</span></div>
                <div class="info-item"><span class="label">分辨率:</span> <span class="value">{{ deviceInfo.screen_size }}</span></div>
                <div class="info-item"><span class="label">密度:</span> <span class="value">{{ deviceInfo.screen_density }}</span></div>
            </div>
            <div v-else class="no-device">正在加载设备信息...</div>
        </div>

        <!-- 目标应用 -->
        <div class="info-section">
            <h3>📦 目标应用</h3>
            <div v-if="targetApp" class="info-item">
                <span class="value">{{ targetApp }}</span>
            </div>
            <div v-else class="info-item"><span class="label">请在手机上打开目标应用</span></div>
            <input v-model="appInput" @keyup.enter="setApp" placeholder="输入包名，如 com.tencent.mm" style="margin-top:6px;padding:4px 8px;background:#0f3460;border:1px solid #2a2a4a;border-radius:4px;color:#e0e0e0;font-size:12px;width:200px;" />
            <button @click="setApp" style="margin-left:6px;padding:4px 10px;background:#e94560;border:none;border-radius:4px;color:#fff;font-size:12px;cursor:pointer;">确认</button>
        </div>

        <!-- 实时性能指标 -->
        <div class="info-section">
            <h3>⚡ 实时性能 <span style="font-size:11px;color:#888;">(2s刷新，支持悬停查看详细说明)</span></h3>
            <div class="metric-row">
                <span class="metric-badge">PSS: <span class="val">{{ fmtMem(metrics.pss_total) }}MB</span></span>
                <span class="metric-badge">Java Heap: <span class="val">{{ fmtMem(metrics.java_heap) }}MB</span></span>
                <span class="metric-badge">Native Heap: <span class="val">{{ fmtMem(metrics.native_heap) }}MB</span></span>
                <span class="metric-badge">CPU: <span class="val">{{ metrics.cpu_percent }}%</span></span>
                <span class="metric-badge">FPS: <span class="val">{{ metrics.estimated_fps }}</span></span>
                <span class="metric-badge">掉帧: <span class="val">{{ metrics.janky_count }}/{{ metrics.frame_count }}</span></span>
            </div>
        </div>

        <!-- 历史趋势图 -->
        <div class="info-section">
            <h3>📈 历史趋势 (5min)</h3>
            <TrendChart chart-id="chart-pss" label="PSS (MB)" color="#e94560" data-key="pss_total" unit="MB" ref="chartPss" />
            <TrendChart chart-id="chart-jheap" label="Java Heap (MB)" color="#f0a500" data-key="java_heap" unit="MB" ref="chartJheap" />
            <TrendChart chart-id="chart-nheap" label="Native Heap (MB)" color="#00b4d8" data-key="native_heap" unit="MB" ref="chartNheap" />
            <TrendChart chart-id="chart-fps" label="FPS" color="#2ecc71" data-key="estimated_fps" unit="" ref="chartFps" />
            <TrendChart chart-id="chart-cpu" label="CPU (%)" color="#9b59b6" data-key="cpu_percent" unit="%" ref="chartCpu" />
        </div>

        <!-- 快捷操作 -->
        <div class="info-section">
            <h3>🔧 快捷操作</h3>
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
            <p>⚠️ {{ deviceError }}</p>
            <p style="margin-top:10px;font-size:13px;color:#666;">
                请确认：<br>
                1. 手机已通过 USB 连接 Mac<br>
                2. 已开启开发者模式 & USB 调试<br>
                3. 已在手机上授权此电脑<br>
                4. 运行 <code>adb devices</code> 确认设备已连接
            </p>
        </div>
    </div>
    `,
    data() {
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
    mounted() {
        this.loadDeviceInfo();
        this.startSSE();
    },
    beforeUnmount() {
        this.stopSSE();
        if (this.refreshTimer) clearInterval(this.refreshTimer);
    },
    methods: {
        async loadDeviceInfo() {
            try {
                const res = await fetch('/api/device/info');
                const data = await res.json();
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
        setApp() {
            const val = this.appInput.trim();
            if (val) {
                this.targetApp = val;
                this.stopSSE();
                this.startSSE();
            }
        },
        startSSE() {
            this.stopSSE();
            const pkgParam = this.targetApp ? `?package_name=${encodeURIComponent(this.targetApp)}` : '';
            this.evtSource = new EventSource(`/api/stream${pkgParam}`);
            this.evtSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.error) return;
                    this.metrics = data;
                    this.trendData.push(data);
                    if (this.trendData.length > 150) {
                        this.trendData = this.trendData.slice(-150);
                    }
                    if (!this.targetApp && data.pss_total > 0) {
                        // 自动检测到前台应用
                    }
                } catch (e) { /* ignore parse errors */ }
            };
            this.evtSource.onerror = () => {
                this.evtSource?.close();
                // 5 秒后重连
                setTimeout(() => this.startSSE(), 5000);
            };

            // 定时刷新趋势图
            if (this.refreshTimer) clearInterval(this.refreshTimer);
            this.refreshTimer = setInterval(() => this.updateCharts(), 2000);
        },
        stopSSE() {
            if (this.evtSource) {
                this.evtSource.close();
                this.evtSource = null;
            }
        },
        updateCharts() {
            if (this.trendData.length > 0) {
                const recent = this.trendData.slice(-150);
                this.$refs.chartPss?.updateChart(recent);
                this.$refs.chartJheap?.updateChart(recent);
                this.$refs.chartNheap?.updateChart(recent);
                this.$refs.chartFps?.updateChart(recent);
                this.$refs.chartCpu?.updateChart(recent);
            }
        },
        fmtMem(kb) {
            if (!kb) return '0.0';
            return (kb / 1024).toFixed(1);
        },
    },
};
