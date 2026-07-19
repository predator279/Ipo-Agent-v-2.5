// Azure Function App URL (Backend API)
const API_BASE_URL = 'https://supreme-ipo-api-123.azurewebsites.net/api';

let currentIpoName = null;
let currentChatHistory = [];

document.addEventListener('DOMContentLoaded', () => {
    fetchIPOs();

    document.getElementById('back-btn').addEventListener('click', () => {
        document.getElementById('ipo-details-section').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');
    });

    // Chat functionality
    document.getElementById('chat-send-btn').addEventListener('click', handleChatSend);
    document.getElementById('chat-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleChatSend();
    });

    document.querySelectorAll('.quick-query-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const query = btn.getAttribute('data-query');
            sendChatMessage(query);
        });
    });
});

async function fetchIPOs() {
    try {
        const response = await fetch(`${API_BASE_URL}/ipos`);
        if (!response.ok) throw new Error("Backend API not responding");
        const data = await response.json();
        
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');

        if (!data || data.length === 0) {
            document.getElementById('current-ipos').innerHTML = '<p style="color: var(--text-muted)">No pre-cached IPOs found in database.</p>';
            return;
        }

        // Calculate sync date
        let maxTime = 0;
        data.forEach(ipo => {
            if (ipo.updated_at) {
                const t = new Date(ipo.updated_at).getTime();
                if (t > maxTime) maxTime = t;
            }
        });
        if (maxTime > 0) {
            document.getElementById('sync-date').innerText = `Data last synced: ${new Date(maxTime).toLocaleString()}`;
        } else {
            document.getElementById('sync-date').innerText = `Data last synced: Unknown`;
        }

        // Group IPOs (Fallback to 'current' if status is missing)
        const currentList = document.getElementById('current-ipos');
        const upcomingList = document.getElementById('upcoming-ipos');
        const pastList = document.getElementById('past-ipos');
        
        currentList.innerHTML = '';
        upcomingList.innerHTML = '';
        pastList.innerHTML = '';

        data.forEach(ipo => {
            const card = document.createElement('div');
            card.className = 'ipo-card';
            
            let dateStr = ipo.updated_at ? new Date(ipo.updated_at).toLocaleDateString() : 'N/A';
            card.innerHTML = `
                <h3>${ipo.ipo_name}</h3>
                <p>Symbol: ${ipo.symbol || 'N/A'}</p>
                <p style="font-size: 0.8rem; margin-top: 0.5rem; opacity: 0.7;">Cached: ${dateStr}</p>
            `;
            card.onclick = () => fetchIPODetails(ipo.ipo_name);
            
            const status = (ipo.status || 'current').toLowerCase();
            if (status === 'upcoming') {
                upcomingList.appendChild(card);
            } else if (status === 'past') {
                pastList.appendChild(card);
            } else {
                currentList.appendChild(card);
            }
        });

        if (!currentList.hasChildNodes()) currentList.innerHTML = '<p style="color: var(--text-muted)">None</p>';
        if (!upcomingList.hasChildNodes()) upcomingList.innerHTML = '<p style="color: var(--text-muted)">None</p>';
        if (!pastList.hasChildNodes()) pastList.innerHTML = '<p style="color: var(--text-muted)">None</p>';

    } catch (err) {
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');
        document.getElementById('current-ipos').innerHTML = `<p style="color:#ef4444;">Failed to load IPOs: ${err.message}</p>`;
    }
}

async function fetchIPODetails(ipoName) {
    try {
        currentIpoName = ipoName;
        currentChatHistory = [];
        resetChatUI();

        document.getElementById('ipo-list-section').classList.add('hidden');
        const detailsSection = document.getElementById('ipo-details-section');
        detailsSection.classList.remove('hidden');
        
        document.getElementById('ipo-title').innerText = ipoName;
        
        // Reset fields
        document.getElementById('metric-issue-size').innerText = '--';
        document.getElementById('metric-price').innerText = '--';
        document.getElementById('metric-lot').innerText = '--';
        document.getElementById('metric-exchange').innerText = '--';
        
        document.getElementById('sentiment-text').innerText = 'Analyzing sentiment...';
        document.querySelector('.sentiment-indicator').className = 'sentiment-indicator';
        
        document.getElementById('financials-head').innerHTML = '';
        document.getElementById('financials-body').innerHTML = '';
        document.getElementById('risks-list').innerHTML = '<li>Loading...</li>';

        const response = await fetch(`${API_BASE_URL}/ipos/${encodeURIComponent(ipoName)}`);
        if (!response.ok) throw new Error("Failed to load details");
        const data = await response.json();
        
        // Populate Metric Cards
        document.getElementById('metric-issue-size').innerText = data.issue_size || 'N/A';
        document.getElementById('metric-price').innerText = data.price_band || data.price || 'N/A';
        document.getElementById('metric-lot').innerText = data.lot_size || 'N/A';
        document.getElementById('metric-exchange').innerText = data.exchange || 'N/A';

        // Populate Sentiment
        if (data.sentiment) {
            let sentimentText = typeof data.sentiment === 'string' ? data.sentiment : (data.sentiment.text || data.sentiment.label || JSON.stringify(data.sentiment));
            document.getElementById('sentiment-text').innerText = sentimentText;
            
            const score = data.sentiment.score || 0;
            const label = (data.sentiment.label || data.sentiment || '').toString().toLowerCase();
            const indicator = document.querySelector('.sentiment-indicator');
            
            if (score > 0 || label.includes('positive') || label.includes('bullish')) {
                indicator.className = 'sentiment-indicator positive';
            } else if (score < 0 || label.includes('negative') || label.includes('bearish')) {
                indicator.className = 'sentiment-indicator negative';
            } else {
                indicator.className = 'sentiment-indicator';
            }
        } else {
            document.getElementById('sentiment-text').innerText = 'No sentiment data available.';
        }

        // Populate Financials
        if (data.financials && Array.isArray(data.financials) && data.financials.length > 0) {
            const headTr = document.getElementById('financials-head');
            const tbody = document.getElementById('financials-body');
            headTr.innerHTML = '';
            tbody.innerHTML = '';
            
            const keys = Object.keys(data.financials[0]);
            keys.forEach(k => {
                const th = document.createElement('th');
                th.innerText = k.replace(/_/g, ' ').toUpperCase();
                headTr.appendChild(th);
            });

            data.financials.forEach(row => {
                const tr = document.createElement('tr');
                keys.forEach(k => {
                    const td = document.createElement('td');
                    td.innerText = row[k] !== null && row[k] !== undefined ? row[k] : '-';
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });
        } else {
            document.getElementById('financials-body').innerHTML = '<tr><td style="color: var(--text-muted);">No financial data available.</td></tr>';
        }

        // Populate Risks
        const risksList = document.getElementById('risks-list');
        risksList.innerHTML = '';
        if (data.key_risks && Array.isArray(data.key_risks)) {
            data.key_risks.forEach(risk => {
                const li = document.createElement('li');
                li.innerText = risk;
                risksList.appendChild(li);
            });
        } else if (typeof data.key_risks === 'string') {
            const li = document.createElement('li');
            li.innerText = data.key_risks;
            risksList.appendChild(li);
        } else {
            risksList.innerHTML = '<li style="color: var(--text-muted);">No risks identified.</li>';
        }

    } catch (err) {
        document.getElementById('ipo-title').innerText = "Error Loading Data";
        document.getElementById('risks-list').innerHTML = `<li style="color:#ef4444;">${err.message}</li>`;
    }
}

function resetChatUI() {
    const chatHistoryEl = document.getElementById('chat-history');
    chatHistoryEl.innerHTML = `
        <div class="chat-message assistant">
            <p>Hello! I can answer questions about this IPO. You can ask me to summarize financials or list top risks.</p>
        </div>
    `;
    document.getElementById('chat-input').value = '';
}

async function handleChatSend() {
    const inputEl = document.getElementById('chat-input');
    const message = inputEl.value.trim();
    if (!message) return;

    inputEl.value = '';
    sendChatMessage(message);
}

async function sendChatMessage(message) {
    if (!currentIpoName) return;

    const chatHistoryEl = document.getElementById('chat-history');
    
    // Add user message to UI
    const userMsgDiv = document.createElement('div');
    userMsgDiv.className = 'chat-message user';
    userMsgDiv.innerHTML = `<p>${message.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>`;
    chatHistoryEl.appendChild(userMsgDiv);
    
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;

    // Add loading indicator
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'chat-message assistant loading';
    loadingDiv.innerHTML = `<p><i>Thinking...</i></p>`;
    chatHistoryEl.appendChild(loadingDiv);
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;

    try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                ipo_name: currentIpoName,
                message: message,
                chat_history: currentChatHistory
            })
        });

        if (!response.ok) throw new Error("Chat failed");
        
        const data = await response.json();
        const answer = data.answer || "Sorry, I couldn't understand that.";

        // Update history
        currentChatHistory.push({ role: 'user', content: message });
        currentChatHistory.push({ role: 'assistant', content: answer });

        // Remove loading
        chatHistoryEl.removeChild(loadingDiv);

        // Add assistant message to UI
        const assistantMsgDiv = document.createElement('div');
        assistantMsgDiv.className = 'chat-message assistant';
        assistantMsgDiv.innerHTML = `<p>${answer.replace(/\n/g, '<br>')}</p>`;
        chatHistoryEl.appendChild(assistantMsgDiv);
        
        chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;

    } catch (err) {
        if(chatHistoryEl.contains(loadingDiv)) {
            chatHistoryEl.removeChild(loadingDiv);
        }
        const errorDiv = document.createElement('div');
        errorDiv.className = 'chat-message assistant';
        errorDiv.innerHTML = `<p style="color:#ef4444;">Error: ${err.message}</p>`;
        chatHistoryEl.appendChild(errorDiv);
        chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
    }
}
