/* global Vue, marked */

var ChatPanel = {
    template: `
    <div class="chat-panel">
        <div class="chat-header">💬 安卓开发助手</div>
        <div class="chat-messages" ref="msgContainer">
            <div v-if="messages.length === 0" class="msg agent">
                <div class="bubble">
                    <p>你好！我是安卓开发助手，可以帮你：</p>
                    <ul>
                        <li>查看设备配置和应用信息</li>
                        <li>分析内存占用和卡顿原因</li>
                        <li>排查崩溃和 ANR 问题</li>
                        <li>截屏、导出堆转储等操作</li>
                    </ul>
                    <p>请先确认手机已通过 USB 连接并开启调试模式。</p>
                </div>
            </div>
            <div v-for="(msg, idx) in messages" :key="idx" :class="'msg ' + msg.role">
                <div class="bubble" v-html="renderMarkdown(msg.content)"></div>
                <div v-if="msg.tools && msg.tools.length" class="tools-info">
                    🔧 {{ msg.tools.map(t => t.tool).join(', ') }}
                </div>
            </div>
            <div v-if="loading" class="loading">⏳ 正在分析...</div>
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
    data() {
        return {
            input: '',
            messages: [],
            loading: false,
            chatHistory: [],
        };
    },
    methods: {
        async sendMessage() {
            const text = this.input.trim();
            if (!text || this.loading) return;

            this.messages.push({ role: 'user', content: text, tools: [] });
            this.input = '';
            this.loading = true;
            this.$nextTick(() => this.scrollToBottom());

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: text,
                        chat_history: this.chatHistory,
                    }),
                });
                const data = await res.json();
                const tools = data.intermediate_steps || [];

                this.messages.push({
                    role: 'agent',
                    content: data.output || '抱歉，没有获取到回复。',
                    tools: tools,
                });

                // 更新对话历史
                this.chatHistory.push(['human', text]);
                this.chatHistory.push(['ai', data.output || '']);
                // 限制历史长度
                if (this.chatHistory.length > 20) {
                    this.chatHistory = this.chatHistory.slice(-20);
                }
            } catch (err) {
                this.messages.push({
                    role: 'agent',
                    content: `❌ 请求失败: ${err.message}`,
                    tools: [],
                });
            } finally {
                this.loading = false;
                this.$nextTick(() => this.scrollToBottom());
            }
        },
        renderMarkdown(text) {
            if (!text) return '';
            try {
                return marked.parse(text);
            } catch {
                return text.replace(/\n/g, '<br>');
            }
        },
        scrollToBottom() {
            const el = this.$refs.msgContainer;
            if (el) el.scrollTop = el.scrollHeight;
        },
    },
};
