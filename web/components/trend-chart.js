/* global Vue, Chart */

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
        return {
            chart: null,
            dataPoints: [],
        };
    },
    mounted() {
        const ctx = this.$refs[this.chartId]?.getContext('2d');
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
                            callback: v => v + this.unit,
                            maxTicksLimit: 4,
                        },
                        grid: { color: '#2a2a4a' },
                    },
                },
            },
        });
    },
    methods: {
        updateChart(dataList) {
            if (!this.chart || !dataList.length) return;
            const labels = dataList.map((_, i) => i);
            const values = dataList.map(d => d[this.dataKey] || 0);
            this.chart.data.labels = labels;
            this.chart.data.datasets[0].data = values;
            this.chart.update('none');
        },
    },
};
