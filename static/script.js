// Azure Function App URL (Backend API)
const API_BASE_URL = 'https://supreme-ipo-api-123.azurewebsites.net/api';

let currentIpoName = null;
let currentChatHistory = [];
let revenueChartInstance = null;
let marginChartInstance = null;

document.addEventListener('DOMContentLoaded', () => {
    fetchIPOs();

    // Tab Navigation Logic
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active from all
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            // Add active to clicked
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-tab');
            document.getElementById(targetId).classList.add('active');
        });
    });

    // Dashboard Buttons
    document.getElementById('back-btn').addEventListener('click', () => {
        document.getElementById('ipo-details-section').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');
        closeChat();
    });

    document.getElementById('open-chat-btn').addEventListener('click', openChat);
    document.getElementById('close-chat-btn').addEventListener('click', closeChat);
    document.getElementById('expand-chat-btn').addEventListener('click', toggleExpandChat);

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
        // You might need to change this URL back to production URL
        const response = await fetch(`${API_BASE_URL}/ipos`);
        if (!response.ok) throw new Error("Backend API not responding");
        const data = await response.json();
        
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');

        if (!data || data.length === 0) {
            document.getElementById('current-tbody').innerHTML = '<tr><td colspan="8">No IPOs found.</td></tr>';
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
        document.getElementById('sync-date').innerText = maxTime > 0 
            ? `Data last synced: ${new Date(maxTime).toLocaleString()}` 
            : `Data last synced: Unknown`;

        const currentTbody = document.getElementById('current-tbody');
        const upcomingTbody = document.getElementById('upcoming-tbody');
        const pastTbody = document.getElementById('past-tbody');
        
        currentTbody.innerHTML = ''; upcomingTbody.innerHTML = ''; pastTbody.innerHTML = '';

        data.forEach(ipo => {
            const status = (ipo.status || 'current').toLowerCase();
            const tr = document.createElement('tr');
            tr.onclick = () => fetchIPODetails(ipo.ipo_name);
            tr.style.cursor = "pointer";

            const meta = ipo.nse_metadata || {};

            if (status === 'upcoming') {
                tr.innerHTML = `
                    <td style="font-weight:600">${meta['Company Name'] || ipo.ipo_name || '-'}</td>
                    <td>${meta['Symbol'] || ipo.symbol || '-'}</td>
                    <td>${meta['Security Type'] || '-'}</td>
                    <td>${meta['Issue Price'] || '-'}</td>
                    <td>${meta['ISSUE START DATE'] || '-'}</td>
                    <td>${meta['ISSUE END DATE'] || '-'}</td>
                    <td><span class="badge" style="border-color:#fbbf24;color:#fbbf24">${meta['STATUS'] || 'Upcoming'}</span></td>
                    <td>${meta['ISSUE SIZE'] || '-'}</td>
                `;
                upcomingTbody.appendChild(tr);
            } else if (status === 'past') {
                tr.innerHTML = `
                    <td style="font-weight:600">${meta['Company Name'] || ipo.ipo_name || '-'}</td>
                    <td>${meta['Symbol'] || ipo.symbol || '-'}</td>
                    <td>${meta['Security Type'] || '-'}</td>
                    <td>${meta['Issue Price'] || '-'}</td>
                    <td>${meta['Price Range'] || '-'}</td>
                    <td>${meta['IPO START DATE'] || '-'}</td>
                    <td>${meta['IPO END DATE'] || '-'}</td>
                    <td>${meta['Listing Date'] || '-'}</td>
                `;
                pastTbody.appendChild(tr);
            } else {
                tr.innerHTML = `
                    <td style="font-weight:600">${meta['Company Name'] || ipo.ipo_name || '-'}</td>
                    <td>${meta['Symbol'] || ipo.symbol || '-'}</td>
                    <td>${meta['Security type'] || '-'}</td>
                    <td>${meta['issuePrice'] || '-'}</td>
                    <td>${meta['Issue Start Date'] || '-'}</td>
                    <td>${meta['Issue End Date'] || '-'}</td>
                    <td><span class="badge" style="border-color:#10b981;color:#10b981">${meta['Status'] || 'Current'}</span></td>
                    <td>${meta['No of Shares Offered'] || '-'}</td>
                `;
                currentTbody.appendChild(tr);
            }
        });

        if (!currentTbody.hasChildNodes()) currentTbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">No Current IPOs</td></tr>';
        if (!upcomingTbody.hasChildNodes()) upcomingTbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">No Upcoming IPOs</td></tr>';
        if (!pastTbody.hasChildNodes()) pastTbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">No Past IPOs</td></tr>';

    } catch (err) {
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');
        document.getElementById('current-tbody').innerHTML = `<tr><td colspan="8" style="color:#ef4444;">Error: ${err.message}</td></tr>`;
    }
}

async function fetchIPODetails(ipoName) {
    try {
        currentIpoName = ipoName;
        currentChatHistory = [];
        resetChatUI();

        document.getElementById('ipo-list-section').classList.add('hidden');
        document.getElementById('ipo-details-section').classList.remove('hidden');
        
        document.getElementById('ipo-title').innerText = ipoName;
        document.getElementById('ipo-sector').innerText = 'Loading...';
        
        // Reset top metrics
        const metrics = ['issue-size', 'price', 'market-cap', 'lot', 'exchange', 'fresh-issue', 'ofs', 'face-value', 'promoter-pre', 'promoter-post'];
        metrics.forEach(m => document.getElementById(`metric-${m}`).innerText = '--');
        
        // Reset Business
        document.getElementById('business-model-content').innerHTML = 'Loading...';

        // Reset Risks
        document.getElementById('risks-list').innerHTML = '<li>Loading...</li>';

        // Fetch Detail
        const response = await fetch(`${API_BASE_URL}/ipos/${encodeURIComponent(ipoName)}`);
        if (!response.ok) throw new Error("Failed to load details");
        const data = await response.json();
        
        const co = data.company_overview || {};
        const meta = data.meta || {};
        const basic = data.basic_info || {};
        const biz = data.business_overview || {};
        const fin = data.financial_summary || {};
        
        document.getElementById('ipo-sector').innerText = data.sector || co.industry || 'Sector unclassified';

        // Populate Top Metrics (handling both NSE live injected and LLM extracted data)
        document.getElementById('metric-issue-size').innerText = basic.issue_size || data.issue_size || '--';
        document.getElementById('metric-price').innerText = basic.price_band || data.price_band || '--';
        document.getElementById('metric-market-cap').innerText = basic.market_cap || data.market_cap || '--';
        document.getElementById('metric-lot').innerText = basic.lot_size || data.lot_size || '--';
        document.getElementById('metric-exchange').innerText = meta.exchange || data.exchange || data.listing_exchange || '--';
        document.getElementById('metric-fresh-issue').innerText = basic.fresh_issue || data.fresh_issue || '--';
        document.getElementById('metric-ofs').innerText = basic.offer_for_sale || data.ofs || '--';
        document.getElementById('metric-face-value').innerText = basic.face_value || data.face_value || '--';
        document.getElementById('metric-promoter-pre').innerText = basic.promoter_holding_pre_pct || data.promoter_holding_pre || '--';
        document.getElementById('metric-promoter-post').innerText = basic.promoter_holding_post_pct || data.promoter_holding_post || '--';

        // Populate Business Model
        let bizHtml = '';
        if (biz.business_model || data.business_model) bizHtml += `<p><strong>Business Model:</strong><br>${biz.business_model || data.business_model}</p>`;
        if (biz.competitive_moat || data.competitive_moat) bizHtml += `<p><strong>Competitive Moat:</strong><br>${biz.competitive_moat || data.competitive_moat}</p>`;
        
        let streams = biz.revenue_streams || data.revenue_streams;
        if (streams && Array.isArray(streams) && streams.length > 0) {
            bizHtml += `<p><strong>Revenue Streams:</strong><br>` + streams.map(r => `<span class="badge" style="margin-right:5px">${r}</span>`).join('') + `</p>`;
        }
        
        // Alternative schema fallback
        if (co.industry && !data.sector) bizHtml += `<p><strong>Industry:</strong><br>${co.industry}</p>`;
        if (co.leadership) bizHtml += `<p><strong>Leadership:</strong><br>${co.leadership}</p>`;
        if (co.ipo_status) bizHtml += `<p><strong>IPO Status:</strong><br>${co.ipo_status}</p>`;
        
        document.getElementById('business-model-content').innerHTML = bizHtml || '<p style="color:var(--text-muted)">No business details available.</p>';

        // Populate Financials Table & Charts
        // Handle new schema `fin.yearly_financials`, older `financials`, and alternate `financial_summary.revenue_fy_latest`
        let financialsData = fin.yearly_financials || data.financials;
        if (!financialsData && data.financial_summary && data.financial_summary.revenue_fy_latest) {
            // Attempt to build a dummy array if it's the alternate schema just so something renders
            financialsData = [{
                year: 'Latest',
                revenue: data.financial_summary.revenue_fy_latest || '-',
                pat: data.financial_summary.profit_after_tax_fy_latest || '-',
                ebitda: '-', ebitda_margin: '-', pat_margin: '-', eps: '-', cash_flow_ops: '-'
            }];
        }
        
        // Ensure mapping for new schema fields in charts logic
        if (financialsData && Array.isArray(financialsData)) {
            financialsData = financialsData.map(f => ({
                ...f,
                ebitda_margin: f.ebitda_margin_pct || f.ebitda_margin,
                pat_margin: f.pat_margin_pct || f.pat_margin,
                cash_flow_ops: f.cfo || f.cash_flow_ops
            }));
        }
        
        renderFinancials(financialsData);

        // Populate Risks
        const risksList = document.getElementById('risks-list');
        risksList.innerHTML = '';
        const risksArr = data.risk_factors || data.key_risks;
        if (risksArr && Array.isArray(risksArr) && risksArr.length > 0) {
            risksArr.forEach(risk => {
                const li = document.createElement('li');
                // new schema has {category, description}, old has string
                li.innerHTML = typeof risk === 'object' ? `<strong>${risk.category}:</strong> ${risk.description}` : risk;
                risksList.appendChild(li);
            });
        } else {
            risksList.innerHTML = '<li style="color: var(--text-muted); background:transparent; border:none">No risks identified.</li>';
        }

    } catch (err) {
        document.getElementById('ipo-title').innerText = "Error Loading Data";
        document.getElementById('risks-list').innerHTML = `<li style="color:#ef4444; background:transparent; border:none">${err.message}</li>`;
    }
}

// ── Chart.js Integration ──────────────────────────────────────────────
function parseNum(val) {
    if (!val) return null;
    let cleaned = String(val).replace(/[₹,\s]/g, "").replace(/(cr|crore|lakh|mn|bn|million|billion|%)/gi, "");
    const parsed = parseFloat(cleaned);
    return isNaN(parsed) ? null : parsed;
}

function renderFinancials(financials) {
    const tbody = document.getElementById('financials-body');
    const thead = document.getElementById('financials-head');
    thead.innerHTML = ''; tbody.innerHTML = '';

    if (revenueChartInstance) { revenueChartInstance.destroy(); revenueChartInstance = null; }
    if (marginChartInstance) { marginChartInstance.destroy(); marginChartInstance = null; }

    if (!financials || !Array.isArray(financials) || financials.length === 0) {
        tbody.innerHTML = '<tr><td style="color:var(--text-muted)">No financial data available.</td></tr>';
        return;
    }

    // Sort by year (ascending for charts)
    const sortedFins = [...financials].sort((a,b) => {
        let yA = parseNum(a.year) || 0;
        let yB = parseNum(b.year) || 0;
        return yA - yB;
    });

    const years = sortedFins.map(f => f.year || 'Unknown');
    const revenues = sortedFins.map(f => parseNum(f.revenue));
    const pats = sortedFins.map(f => parseNum(f.pat));
    const ebitdaMargins = sortedFins.map(f => parseNum(f.ebitda_margin));
    const patMargins = sortedFins.map(f => parseNum(f.pat_margin));

    // Chart 1: Revenue vs PAT
    const ctxRev = document.getElementById('revenueChart').getContext('2d');
    revenueChartInstance = new Chart(ctxRev, {
        type: 'bar',
        data: {
            labels: years,
            datasets: [
                { label: 'Revenue (₹ Cr)', data: revenues, backgroundColor: '#3b82f6', borderRadius: 4 },
                { label: 'PAT (₹ Cr)', data: pats, backgroundColor: '#10b981', borderRadius: 4 }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { labels: { color: '#94a3b8' } }, title: { display: true, text: 'Revenue vs PAT', color: '#f8fafc' } },
            scales: {
                x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });

    // Chart 2: Margin Trends
    const ctxMar = document.getElementById('marginChart').getContext('2d');
    marginChartInstance = new Chart(ctxMar, {
        type: 'line',
        data: {
            labels: years,
            datasets: [
                { label: 'EBITDA Margin %', data: ebitdaMargins, borderColor: '#fbbf24', tension: 0.4, fill: false },
                { label: 'PAT Margin %', data: patMargins, borderColor: '#10b981', tension: 0.4, fill: false }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { labels: { color: '#94a3b8' } }, title: { display: true, text: 'Margin Trends (%)', color: '#f8fafc' } },
            scales: {
                x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });

    // Render Table (Descending order usually looks better for tables)
    const reversedFins = [...sortedFins].reverse();
    const cols = ['Year', 'Revenue', 'EBITDA', 'EBITDA Margin', 'PAT', 'PAT Margin', 'EPS', 'CFO'];
    cols.forEach(c => {
        const th = document.createElement('th'); th.innerText = c; thead.appendChild(th);
    });

    reversedFins.forEach(f => {
        const tr = document.createElement('tr');
        const vals = [f.year, f.revenue, f.ebitda, f.ebitda_margin, f.pat, f.pat_margin, f.eps, f.cash_flow_ops];
        vals.forEach(v => {
            const td = document.createElement('td'); td.innerText = v || '-'; tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

// ── Chat Side Panel ──────────────────────────────────────────────────
function openChat() {
    const sidepanel = document.getElementById('chat-sidepanel');
    sidepanel.classList.remove('hidden');
    // slight delay to ensure transition triggers
    setTimeout(() => { sidepanel.classList.add('open'); }, 10);
}

function closeChat() {
    const sidepanel = document.getElementById('chat-sidepanel');
    sidepanel.classList.remove('open');
    sidepanel.classList.remove('expanded');
    setTimeout(() => { sidepanel.classList.add('hidden'); }, 300);
}

function toggleExpandChat() {
    const sidepanel = document.getElementById('chat-sidepanel');
    sidepanel.classList.toggle('expanded');
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
    
    // Add user msg
    const userMsgDiv = document.createElement('div');
    userMsgDiv.className = 'chat-message user';
    userMsgDiv.innerHTML = `<p>${message.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>`;
    chatHistoryEl.appendChild(userMsgDiv);
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;

    // Loading indicator
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'chat-message assistant loading';
    loadingDiv.innerHTML = `<p><i>Thinking...</i></p>`;
    chatHistoryEl.appendChild(loadingDiv);
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;

    try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ipo_name: currentIpoName, message: message, chat_history: currentChatHistory })
        });

        if (!response.ok) throw new Error("Chat failed");
        const data = await response.json();
        const answer = data.answer || "Sorry, I couldn't understand that.";

        currentChatHistory.push({ role: 'user', content: message });
        currentChatHistory.push({ role: 'assistant', content: answer });

        chatHistoryEl.removeChild(loadingDiv);

        const assistantMsgDiv = document.createElement('div');
        assistantMsgDiv.className = 'chat-message assistant';
        assistantMsgDiv.innerHTML = `<p>${answer.replace(/\n/g, '<br>')}</p>`;
        chatHistoryEl.appendChild(assistantMsgDiv);
        chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;

    } catch (err) {
        if(chatHistoryEl.contains(loadingDiv)) chatHistoryEl.removeChild(loadingDiv);
        const errorDiv = document.createElement('div');
        errorDiv.className = 'chat-message assistant';
        errorDiv.innerHTML = `<p style="color:#ef4444;">Error: ${err.message}</p>`;
        chatHistoryEl.appendChild(errorDiv);
        chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
    }
}
