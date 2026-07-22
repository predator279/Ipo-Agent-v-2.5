// Azure Function App URL (Backend API)
const API_BASE_URL = 'https://supreme-ipo-api-123.azurewebsites.net/api';

let currentIpoName = null;
let currentChatHistory = [];
let revenueChartInstance = null;
let marginChartInstance = null;
let objectsChartInstance = null;
let sentimentChartInstance = null;

document.addEventListener('DOMContentLoaded', () => {
    lucide.createIcons();
    initTheme();
    fetchIPOs();

    // Fix hero lottie squish/blur: force aspect-preserving fit + full-res rendering.
    // These must be set AFTER the specific instance has loaded (not just after the
    // custom element class is registered), or a fast/cached load will apply them
    // too early and they'll silently be dropped.
    const heroLottie = document.getElementById('hero-lottie');
    if (heroLottie) {
        const applyHeroLottieFixes = () => {
            heroLottie.layout = { fit: 'contain', align: [0.5, 0.5] };
            heroLottie.renderConfig = { devicePixelRatio: window.devicePixelRatio || 1, autoResize: true };
        };
        if (heroLottie.dotLottie) {
            // Already loaded (e.g. very fast/cached load beat this script)
            applyHeroLottieFixes();
        } else {
            heroLottie.addEventListener('load', applyHeroLottieFixes, { once: true });
        }
    }

    // Theme Toggle Logic
    document.getElementById('theme-toggle').addEventListener('click', toggleTheme);

    // Main Tab Navigation Logic
    document.querySelectorAll('#ipo-list-section .tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#ipo-list-section .tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('#ipo-list-section .tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(btn.getAttribute('data-tab')).classList.add('active');
        });
    });



    // Strengths & Risks Toggle
    document.getElementById('toggle-strengths-btn').addEventListener('click', () => {
        document.getElementById('toggle-strengths-btn').classList.add('active');
        document.getElementById('toggle-risks-btn').classList.remove('active');
        document.getElementById('strengths-content').classList.add('active');
        document.getElementById('risks-content').classList.remove('active');
    });
    
    document.getElementById('toggle-risks-btn').addEventListener('click', () => {
        document.getElementById('toggle-risks-btn').classList.add('active');
        document.getElementById('toggle-strengths-btn').classList.remove('active');
        document.getElementById('risks-content').classList.add('active');
        document.getElementById('strengths-content').classList.remove('active');
    });

    // Dashboard Buttons
    document.getElementById('back-btn').addEventListener('click', () => {
        document.getElementById('ipo-details-section').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');
        closeChat();
    });

    document.getElementById('open-chat-btn').addEventListener('click', openChat);
    document.getElementById('close-chat-btn').addEventListener('click', closeChat);
    document.getElementById('chat-input').addEventListener('keypress', (e) => { if(e.key==='Enter') handleChatSend(); });
    document.getElementById('chat-send-btn').addEventListener('click', handleChatSend);

    document.querySelectorAll('.quick-query-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('chat-input').value = btn.innerText;
            handleChatSend();
        });
    });
    
    // Tab switching (both horizontal and vertical rail)
    const allTabBtns = document.querySelectorAll('.tab-btn, .rail-btn');
    allTabBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            const target = e.currentTarget.getAttribute('data-tab');
            
            // Remove active from all buttons
            allTabBtns.forEach(b => b.classList.remove('active'));
            // Add active to the clicked target in both navigations
            document.querySelectorAll(`.tab-btn[data-tab="${target}"], .rail-btn[data-tab="${target}"]`).forEach(b => b.classList.add('active'));
            
            // Switch content
            document.querySelectorAll('#ipo-details-section .tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(target).classList.add('active');
        });
    });

    initChatResizer();
});

function initTheme() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
        document.getElementById('theme-icon').setAttribute('data-lucide', 'sun');
    } else {
        document.documentElement.removeAttribute('data-theme');
        document.getElementById('theme-icon').setAttribute('data-lucide', 'moon');
    }
    lucide.createIcons();
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    if (current === 'dark') {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('theme', 'light');
        document.getElementById('theme-icon').setAttribute('data-lucide', 'moon');
    } else {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('theme', 'dark');
        document.getElementById('theme-icon').setAttribute('data-lucide', 'sun');
    }
    lucide.createIcons();
}

function getChartColors() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return {
        text: isDark ? '#94a3b8' : '#6b7280',
        grid: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)',
        title: isDark ? '#f8fafc' : '#111827'
    };
}

async function fetchIPOs() {
    try {
        const response = await fetch(`${API_BASE_URL}/ipos`);
        if (!response.ok) throw new Error("Backend API not responding");
        const data = await response.json();
        
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');

        if (!data || data.length === 0) {
            document.getElementById('current-tbody').innerHTML = '<tr><td colspan="8">No IPOs found.</td></tr>';
            return;
        }

        let maxTime = 0;
        data.forEach(ipo => {
            if (ipo.updated_at) {
                const t = new Date(ipo.updated_at).getTime();
                if (t > maxTime) maxTime = t;
            }
        });
        // document.getElementById('sync-date').innerHTML = maxTime > 0 
        //     ? `<i data-lucide="refresh-cw" style="width: 14px; height: 14px;"></i> Data last synced: ${new Date(maxTime).toLocaleString()}` 
        //     : `<i data-lucide="refresh-cw" style="width: 14px; height: 14px;"></i> Data last synced: Unknown`;
        lucide.createIcons();

        const currentTbody = document.getElementById('current-tbody');
        const upcomingTbody = document.getElementById('upcoming-tbody');
        const pastTbody = document.getElementById('past-tbody');
        
        currentTbody.innerHTML = ''; upcomingTbody.innerHTML = ''; pastTbody.innerHTML = '';

        data.forEach(ipo => {
            const status = (ipo.status || 'current').toLowerCase();
            const tr = document.createElement('tr');
            tr.onclick = () => fetchIPODetails(ipo.ipo_name);
            const meta = ipo.nse_metadata || {};

            if (status === 'upcoming') {
                tr.innerHTML = `
                    <td style="font-weight:600; color:var(--text-main);">${meta['Company Name'] || ipo.ipo_name || '-'}</td>
                    <td>${meta['Symbol'] || ipo.symbol || '-'}</td>
                    <td>${meta['Security Type'] || '-'}</td>
                    <td>${meta['Issue Price'] || '-'}</td>
                    <td>${meta['ISSUE START DATE'] || '-'}</td>
                    <td>${meta['ISSUE END DATE'] || '-'}</td>
                    <td><span class="badge" style="border-color:var(--sentiment-neutral);color:var(--sentiment-neutral)">${meta['STATUS'] || 'Upcoming'}</span></td>
                    <td>${meta['ISSUE SIZE'] || '-'}</td>
                `;
                upcomingTbody.appendChild(tr);
            } else if (status === 'past') {
                tr.innerHTML = `
                    <td style="font-weight:600; color:var(--text-main);">${meta['Company Name'] || ipo.ipo_name || '-'}</td>
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
                    <td style="font-weight:600; color:var(--text-main);">${meta['Company Name'] || ipo.ipo_name || '-'}</td>
                    <td>${meta['Symbol'] || ipo.symbol || '-'}</td>
                    <td>${meta['Security type'] || '-'}</td>
                    <td>${meta['issuePrice'] || '-'}</td>
                    <td>${meta['Issue Start Date'] || '-'}</td>
                    <td>${meta['Issue End Date'] || '-'}</td>
                    <td><span class="badge" style="border-color:var(--sentiment-positive);color:var(--sentiment-positive)">${meta['Status'] || 'Current'}</span></td>
                    <td>${meta['No of Shares Offered'] || '-'}</td>
                `;
                currentTbody.appendChild(tr);
            }
        });

    } catch (err) {
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');
        document.getElementById('current-tbody').innerHTML = `<tr><td colspan="8" style="color:var(--sentiment-negative);">Error: ${err.message}</td></tr>`;
    }
}

async function fetchIPODetails(ipoName) {
    try {
        currentIpoName = ipoName;
        currentChatHistory = [];
        resetChatUI();

        document.getElementById('ipo-list-section').classList.add('hidden');
        document.getElementById('ipo-details-section').classList.remove('hidden');
        document.getElementById('dashboard-content').classList.add('hidden');
        document.getElementById('dashboard-loader').classList.remove('hidden');
        
        // Reset Tabs to Overview
        const allTabBtns = document.querySelectorAll('.tab-btn, .rail-btn');
        allTabBtns.forEach(b => b.classList.remove('active'));
        document.querySelectorAll('#ipo-details-section .tab-content').forEach(c => c.classList.remove('active'));
        document.querySelectorAll(`.tab-btn[data-tab="dash-overview"], .rail-btn[data-tab="dash-overview"]`).forEach(b => b.classList.add('active'));
        document.getElementById('dash-overview').classList.add('active');
        
        document.getElementById('ipo-title').innerText = ipoName;
        document.getElementById('ipo-sector').innerText = 'Loading...';
        
        const metrics = ['issue-size', 'price', 'market-cap', 'lot', 'exchange', 'fresh-issue', 'ofs', 'face-value'];
        metrics.forEach(m => document.getElementById(`metric-${m}`).innerText = '--');
        
        document.getElementById('business-model-content').innerHTML = 'Loading...';

        document.getElementById('key-metrics-section-container').classList.add('hidden');
        document.getElementById('peer-comparison-section-container').classList.add('hidden');
        document.getElementById('objects-issue-section-container').classList.add('hidden');
        document.getElementById('management-section-container').classList.add('hidden');
        document.getElementById('sentiment-section-container').classList.add('hidden');
        
        document.getElementById('strengths-grouped-content').innerHTML = '<span style="color:var(--text-muted)">Loading strengths...</span>';
        document.getElementById('risks-grouped-content').innerHTML = '<span style="color:var(--text-muted)">Loading risks...</span>';

        if (objectsChartInstance) { objectsChartInstance.destroy(); objectsChartInstance = null; }
        if (sentimentChartInstance) { sentimentChartInstance.destroy(); sentimentChartInstance = null; }

        const response = await fetch(`${API_BASE_URL}/ipos/${encodeURIComponent(ipoName)}`);
        if (!response.ok) throw new Error("Failed to load details");
        const data = await response.json();
        
        document.getElementById('dashboard-loader').classList.add('hidden');
        document.getElementById('dashboard-content').classList.remove('hidden');
        
        const co = data.company_overview || {};
        const meta = data.meta || {};
        const basic = data.basic_info || {};
        const biz = data.business_overview || {};
        const fin = data.financial_summary || {};
        
        document.getElementById('ipo-sector').innerText = data.sector || co.industry || 'Sector unclassified';

        document.getElementById('metric-issue-size').innerText = basic.issue_size || data.issue_size || '--';
        document.getElementById('metric-price').innerText = basic.price_band || data.price_band || '--';
        document.getElementById('metric-market-cap').innerText = basic.market_cap || data.market_cap || '--';
        document.getElementById('metric-lot').innerText = basic.lot_size || data.lot_size || '--';
        document.getElementById('metric-exchange').innerText = meta.exchange || data.exchange || data.listing_exchange || '--';
        document.getElementById('metric-fresh-issue').innerText = basic.fresh_issue || data.fresh_issue || '--';
        document.getElementById('metric-ofs').innerText = basic.offer_for_sale || data.ofs || '--';
        document.getElementById('metric-face-value').innerText = basic.face_value || data.face_value || '--';

        // Styled About Cards
        let bizHtml = '';
        if (biz.business_model || data.business_model) {
            bizHtml += `<div style="margin-bottom: 1.5rem; padding: 1.25rem; background: var(--bg-subcard); border: 1px solid var(--border); border-radius: 8px;">
                            <h4 style="margin:0 0 0.5rem 0; display:flex; align-items:center; gap:0.5rem; color:var(--text-main);"><i data-lucide="building" style="width:16px;height:16px;color:var(--accent);"></i> Business Model</h4>
                            <p style="margin:0;">${biz.business_model || data.business_model}</p>
                        </div>`;
        }
        if (biz.competitive_moat || data.competitive_moat) {
            bizHtml += `<div style="margin-bottom: 1.5rem; padding: 1.25rem; background: var(--bg-subcard); border: 1px solid var(--border); border-radius: 8px;">
                            <h4 style="margin:0 0 0.5rem 0; display:flex; align-items:center; gap:0.5rem; color:var(--text-main);"><i data-lucide="shield" style="width:16px;height:16px;color:var(--accent);"></i> Competitive Moat</h4>
                            <p style="margin:0;">${biz.competitive_moat || data.competitive_moat}</p>
                        </div>`;
        }
        
        let streams = biz.revenue_streams || data.revenue_streams;
        if (streams && Array.isArray(streams) && streams.length > 0) {
            bizHtml += `<div style="margin-bottom: 1.5rem; padding: 1.25rem; background: var(--bg-subcard); border: 1px solid var(--border); border-radius: 8px;">
                            <h4 style="margin:0 0 0.75rem 0; display:flex; align-items:center; gap:0.5rem; color:var(--text-main);"><i data-lucide="pie-chart" style="width:16px;height:16px;color:var(--accent);"></i> Revenue Streams</h4>
                            ` + streams.map(r => `<span class="badge" style="margin-right:5px; margin-bottom:5px;">${r}</span>`).join('') + `
                        </div>`;
        }
        
        document.getElementById('business-model-content').innerHTML = bizHtml || '<p style="color:var(--text-muted)">No business details available.</p>';

        let financialsData = fin.yearly_financials || data.financials;
        if (!financialsData && data.financial_summary && data.financial_summary.revenue_fy_latest) {
            financialsData = [{
                year: 'Latest', revenue: data.financial_summary.revenue_fy_latest, pat: data.financial_summary.profit_after_tax_fy_latest,
                ebitda: null, ebitda_margin_pct: null, pat_margin_pct: null, eps: null, cfo: null
            }];
        }
        if (financialsData && Array.isArray(financialsData)) {
            financialsData = financialsData.map(f => ({
                ...f, ebitda_margin_pct: f.ebitda_margin_pct !== undefined ? f.ebitda_margin_pct : f.ebitda_margin,
                pat_margin_pct: f.pat_margin_pct !== undefined ? f.pat_margin_pct : f.pat_margin,
                cfo: f.cfo !== undefined ? f.cfo : f.cash_flow_ops
            }));
        }
        
        renderFinancials(financialsData);

        // 1. Key Metrics
        const keyMetrics = fin.key_metrics || {};
        const bsArr = keyMetrics.balance_sheet || [];
        const rrArr = keyMetrics.return_ratios || [];
        const vmArr = keyMetrics.valuation_multiples || [];
        const skArr = keyMetrics.sector_kpis || [];
        
        if (bsArr.length || rrArr.length || vmArr.length || skArr.length) {
            document.getElementById('key-metrics-section-container').classList.remove('hidden');
            
            if (bsArr.length) {
                document.getElementById('metrics-col-bs').classList.remove('hidden');
                document.getElementById('metrics-bs-list').innerHTML = bsArr.map(x => `<li><strong>${x.label}:</strong> <span style="color:var(--text-main)">${x.value}</span></li>`).join('');
            } else { document.getElementById('metrics-col-bs').classList.add('hidden'); }
            
            if (rrArr.length || vmArr.length) {
                document.getElementById('metrics-col-ratios').classList.remove('hidden');
                if (rrArr.length) {
                    document.getElementById('metrics-ratios-sub').classList.remove('hidden');
                    document.getElementById('metrics-ratios-list').innerHTML = rrArr.map(x => `<li><strong>${x.label}:</strong> <span style="color:var(--text-main)">${x.value}</span></li>`).join('');
                } else { document.getElementById('metrics-ratios-sub').classList.add('hidden'); }
                if (vmArr.length) {
                    document.getElementById('metrics-valuation-sub').classList.remove('hidden');
                    document.getElementById('metrics-valuation-list').innerHTML = vmArr.map(x => `<li><strong>${x.label}:</strong> <span style="color:var(--text-main)">${x.value}</span></li>`).join('');
                } else { document.getElementById('metrics-valuation-sub').classList.add('hidden'); }
            } else { document.getElementById('metrics-col-ratios').classList.add('hidden'); }
            
            if (skArr.length) {
                document.getElementById('metrics-col-kpis').classList.remove('hidden');
                document.getElementById('metrics-kpis-list').innerHTML = skArr.map(x => `<li><strong>${x.label}:</strong> <span style="color:var(--text-main)">${x.value}</span></li>`).join('');
            } else { document.getElementById('metrics-col-kpis').classList.add('hidden'); }
        }

        // 2. Peer Comparison
        const peers = data.peer_comparison || [];
        if (peers.length > 0) {
            document.getElementById('peer-comparison-section-container').classList.remove('hidden');
            document.getElementById('peer-tbody').innerHTML = peers.map(p => `
                <tr>
                    <td style="color:var(--text-main); font-weight:500;">${p.name || '—'}</td>
                    <td>${p.pe !== null && p.pe !== undefined ? p.pe : '—'}</td>
                    <td>${p.revenue !== null && p.revenue !== undefined ? p.revenue : '—'}</td>
                    <td>${p.pat_margin_pct !== null && p.pat_margin_pct !== undefined ? p.pat_margin_pct : '—'}</td>
                </tr>
            `).join('');
        }

        // 3. Objects of the Issue
        const objects = data.objects_of_issue || {};
        const objBreakdown = objects.breakdown || [];
        const objCategories = objects.categories || [];
        
        if (objects.total_amount || objBreakdown.length || objCategories.length) {
            document.getElementById('objects-issue-section-container').classList.remove('hidden');
            const chartData = objBreakdown.map(x => ({ ...x, parsedAmount: parseNum(x.amount) }))
                                          .filter(x => x.parsedAmount !== null && x.parsedAmount !== undefined && !isNaN(x.parsedAmount));
            if (chartData.length > 0) {
                document.getElementById('objects-chart-container').classList.remove('hidden');
                document.getElementById('objects-no-chart').classList.add('hidden');
                
                const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
                const ctxObj = document.getElementById('objectsChart').getContext('2d');
                objectsChartInstance = new Chart(ctxObj, {
                    type: 'doughnut',
                    data: {
                        labels: chartData.map(x => x.purpose || 'Unknown'),
                        datasets: [{
                            data: chartData.map(x => x.parsedAmount),
                            backgroundColor: ['#10b981', '#3b82f6', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4'],
                            borderWidth: 0
                        }]
                    },
                    options: {
                        responsive: true, maintainAspectRatio: false,
                        animation: { duration: 800, easing: 'easeOutQuart' },
                        plugins: { legend: { position: 'right', labels: { color: isDark ? '#94a3b8' : '#6b7280' } }, title: { display: true, text: 'Allocation (₹ in Cr)', color: isDark ? '#f8fafc' : '#111827' } }
                    }
                });
            } else {
                document.getElementById('objects-chart-container').classList.add('hidden');
                document.getElementById('objects-no-chart').classList.remove('hidden');
            }
            
            if (objCategories.length > 0) {
                document.getElementById('objects-categories-list').innerHTML = objCategories.map(c => `<span class="badge">${c}</span>`).join('');
            } else {
                document.getElementById('objects-categories-list').innerHTML = '<span style="color:var(--text-muted)">No categories specified.</span>';
            }
        }

        // 4. Management
        const mgt = data.management || {};
        const keyMgt = mgt.key_management || [];
        const promoters = mgt.promoters || [];
        const litigations = mgt.litigations || {};
        
        if (keyMgt.length || promoters.length || litigations.status_summary || litigations.details) {
            document.getElementById('management-section-container').classList.remove('hidden');
            
            if (keyMgt.length) {
                document.getElementById('mgmt-key-col').classList.remove('hidden');
                document.getElementById('mgmt-key-list').innerHTML = keyMgt.map(m => `<span class="badge" style="display:flex; justify-content:flex-start; padding: 0.75rem 1rem;"><i data-lucide="user" style="width:16px;height:16px;margin-right:0.5rem;color:var(--accent);"></i> <strong style="color:var(--text-main)">${m.name}</strong> <span style="margin-left:auto;color:var(--text-muted);font-weight:400;">${m.role}</span></span>`).join('');
            } else { document.getElementById('mgmt-key-col').classList.add('hidden'); }
            
            if (promoters.length) {
                document.getElementById('mgmt-promoters-col').classList.remove('hidden');
                document.getElementById('mgmt-promoters-list').innerHTML = promoters.map(p => {
                    let typeStr = p.type ? ` (${p.type})` : '';
                    return `<span class="badge" style="display:flex; justify-content:flex-start; padding: 0.75rem 1rem;"><i data-lucide="building" style="width:16px;height:16px;margin-right:0.5rem;color:var(--accent);"></i> <strong style="color:var(--text-main)">${p.name}</strong><span style="margin-left:auto;color:var(--text-muted);font-weight:400;">${typeStr}</span></span>`;
                }).join('');
            } else { document.getElementById('mgmt-promoters-col').classList.add('hidden'); }
            
            if (litigations.status_summary || litigations.details) {
                document.getElementById('mgmt-litigations').classList.remove('hidden');
                let litHtml = '<strong style="color:var(--text-main); display:flex; align-items:center; gap:0.25rem;"><i data-lucide="scale" style="width:16px;height:16px;color:var(--sentiment-negative);"></i> Litigations:</strong> ';
                if (litigations.status_summary) litHtml += litigations.status_summary + ' ';
                if (litigations.details) litHtml += `<span style="color:var(--text-muted)">${litigations.details}</span>`;
                document.getElementById('mgmt-litigations').innerHTML = litHtml;
            } else { document.getElementById('mgmt-litigations').classList.add('hidden'); }
        }

        // 5. Strengths & Risks (Positives & Cons)
        const sent = data.sentiment || {};
        
        // Sentiment Tab -> Positives and Concerns layout
        const pos = sent.positives || [];
        const cons = sent.negatives || [];
        
        if (pos.length > 0) {
            document.getElementById('sentiment-positives-grid').innerHTML = pos.map(p => `<li><i data-lucide="check-circle-2" style="width:18px;height:18px;"></i> <span style="color:var(--text-main)">${p}</span></li>`).join('');
        } else {
            document.getElementById('sentiment-positives-grid').innerHTML = '<li><span style="color:var(--text-muted)">No specific positives listed.</span></li>';
        }
        
        if (cons.length > 0) {
            document.getElementById('sentiment-negatives-grid').innerHTML = cons.map(c => `<li><i data-lucide="alert-triangle" style="width:18px;height:18px;"></i> <span style="color:var(--text-main)">${c}</span></li>`).join('');
        } else {
            document.getElementById('sentiment-negatives-grid').innerHTML = '<li><span style="color:var(--text-muted)">No specific concerns listed.</span></li>';
        }

        // Analyst Summary and Sources
        if (sent.summary && Array.isArray(sent.summary) && sent.summary.length > 0) {
            document.getElementById('sentiment-analyst-summary-container').classList.remove('hidden');
            document.getElementById('sentiment-analyst-summary').innerHTML = sent.summary.map(s => `<li style="margin-bottom:0.25rem;">${s}</li>`).join('');
        } else {
            document.getElementById('sentiment-analyst-summary-container').classList.add('hidden');
        }

        if (sent.articles && Array.isArray(sent.articles) && sent.articles.length > 0) {
            document.getElementById('sentiment-sources-container').classList.remove('hidden');
            
            const articles = sent.articles;
            let tavilyArticles = [];
            let googleNewsArticles = [];
            let otherArticles = [];
            
            articles.forEach(a => {
                const s = a.source ? a.source.toLowerCase() : '';
                if (s.includes('tavily')) {
                    tavilyArticles.push(a);
                } else if (s.includes('google news')) {
                    googleNewsArticles.push(a);
                } else {
                    otherArticles.push(a);
                }
            });
            
            let articlesHtml = '';
            
            const renderArticleList = (title, list) => {
                if (list.length === 0) return '';
                return `<details style="margin-top: 0.5rem; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-subcard);">
                            <summary style="padding: 0.75rem; cursor: pointer; color: var(--accent); font-weight: 600; display:flex; align-items:center; gap:0.5rem;">
                                <i data-lucide="chevron-down" style="width:16px;height:16px;"></i> ${title} (${list.length})
                            </summary>
                            <div style="padding: 0 1rem 1rem 1rem;">
                                <ul style="margin-top:0; padding-left: 0; list-style: none; display: flex; flex-direction: column; gap: 0.75rem;">
                                    ${list.map(a => {
                                        const url = a.url ? a.url : '#';
                                        const publisher = a.source ? a.source.replace(/^Tavily\/|^Google News\//i, '') : '';
                                        const desc = a.description ? `<p style="font-size:0.8rem; color:var(--text-muted); margin: 0.25rem 0 0 0;">${a.description}</p>` : '';
                                        return `<li><a href="${url}" target="_blank" style="color: var(--accent); text-decoration: none; display: flex; align-items: center; gap: 0.25rem; font-weight:500;"><i data-lucide="external-link" style="width:14px;height:14px;"></i> ${a.title || url}</a> ${publisher ? `<span style="color:var(--text-muted);font-size:0.75rem;">— ${publisher}</span>` : ''}${desc}</li>`;
                                    }).join('')}
                                </ul>
                            </div>
                        </details>`;
            };
            
            articlesHtml += renderArticleList('Tavily', tavilyArticles);
            articlesHtml += renderArticleList('Google News', googleNewsArticles);
            articlesHtml += renderArticleList('Other Sources', otherArticles);
            
            document.getElementById('sentiment-articles-list').innerHTML = articlesHtml;
        } else {
            document.getElementById('sentiment-sources-container').classList.add('hidden');
        }

        // Map Strengths to details dropdown using data.key_strengths
        const strengthsArr = data.key_strengths || data.strengths || [];
        if (strengthsArr && Array.isArray(strengthsArr) && strengthsArr.length > 0) {
            const groups = {};
            strengthsArr.forEach(s => {
                const c = s.category || 'Other Strengths';
                if (!groups[c]) groups[c] = [];
                groups[c].push(s.description);
            });
            
            let sHtml = '';
            for (const [cat, descs] of Object.entries(groups)) {
                const topDesc = descs.slice(0, 1);
                const restDesc = descs.slice(1);
                
                sHtml += `
                    <div class="strength-category" style="margin-bottom: 1.5rem;">
                        <h4 style="margin-top:0; font-size:1.05rem; color:var(--text-main); margin-bottom: 0.75rem;">${cat}</h4>
                        <ul class="clean-list positive" style="margin-bottom: 0.5rem;">
                            ${topDesc.map(d => `<li><i data-lucide="check-circle-2" style="width:18px;height:18px;"></i> <span style="color:var(--text-main)">${d}</span></li>`).join('')}
                        </ul>`;
                
                if (restDesc.length > 0) {
                    sHtml += `
                        <details style="border: 1px solid var(--border); border-radius: 8px; background: var(--bg-subcard);">
                            <summary style="padding: 0.75rem 1rem; cursor: pointer; color: var(--accent); font-weight: 500; display:flex; align-items:center; gap:0.5rem; font-size:0.9rem;">
                                <i data-lucide="chevron-down" style="width:16px;height:16px;"></i> Show ${restDesc.length} more in ${cat}
                            </summary>
                            <div style="padding: 0 1rem 1rem 1rem;">
                                <ul class="clean-list positive" style="margin-top:0;">
                                    ${restDesc.map(d => `<li><i data-lucide="check-circle-2" style="width:18px;height:18px;"></i> <span style="color:var(--text-main)">${d}</span></li>`).join('')}
                                </ul>
                            </div>
                        </details>`;
                }
                sHtml += `</div>`;
            }
            document.getElementById('strengths-grouped-content').innerHTML = sHtml;
        } else {
            document.getElementById('strengths-grouped-content').innerHTML = '<span style="color:var(--text-muted)">No key strengths specified.</span>';
        }

        // Map Risks to details dropdown
        const risksArr = data.risk_factors || data.key_risks || [];
        if (risksArr && Array.isArray(risksArr) && risksArr.length > 0) {
            const risksContent = document.getElementById('risks-grouped-content');
            if (typeof risksArr[0] === 'object' && risksArr[0].category) {
                const groups = {};
                risksArr.forEach(r => {
                    const c = r.category || 'Other Risks';
                    if (!groups[c]) groups[c] = [];
                    groups[c].push(r.description);
                });
                
                let risksHtml = '';
                for (const [cat, descs] of Object.entries(groups)) {
                    const topDesc = descs.slice(0, 1); // 1 per category
                    const restDesc = descs.slice(1);
                    
                    risksHtml += `
                        <div class="risk-category" style="margin-bottom: 1.5rem;">
                            <h4 style="margin: 0 0 0.75rem 0; color: var(--text-main); font-size: 1rem; display:flex; align-items:center; gap:0.5rem;"><i data-lucide="folder" style="width:16px;height:16px;color:var(--text-muted);"></i> ${cat}</h4>
                            <ul class="clean-list negative">
                                ${topDesc.map(d => `<li><i data-lucide="alert-triangle" style="width:18px;height:18px;"></i> <span style="color:var(--text-main)">${d}</span></li>`).join('')}
                            </ul>
                            `;
                    
                    if (restDesc.length > 0) {
                        risksHtml += `
                            <details style="margin-top: 0.5rem; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-subcard);">
                                <summary style="padding: 0.75rem 1rem; cursor: pointer; color: var(--sentiment-negative); font-weight: 500; font-size: 0.9rem; display:flex; align-items:center; gap:0.5rem;">
                                    <i data-lucide="chevron-down" style="width:16px;height:16px;"></i> Show ${restDesc.length} More ${cat}
                                </summary>
                                <div style="padding: 0 1rem 1rem 1rem;">
                                    <ul class="clean-list negative" style="margin-top:0;">
                                        ${restDesc.map(d => `<li><i data-lucide="alert-triangle" style="width:18px;height:18px;"></i> <span style="color:var(--text-main)">${d}</span></li>`).join('')}
                                    </ul>
                                </div>
                            </details>
                        `;
                    }
                    risksHtml += `</div>`;
                }
                risksContent.innerHTML = risksHtml;
            } else {
                const topDesc = risksArr.slice(0, 2);
                const restDesc = risksArr.slice(2);
                
                let rHtml = `<ul class="clean-list negative">${topDesc.map(r => `<li><i data-lucide="alert-triangle" style="width:18px;height:18px;"></i> <span style="color:var(--text-main)">${r}</span></li>`).join('')}</ul>`;
                
                if (restDesc.length > 0) {
                     rHtml += `<details style="margin-top: 1rem; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-subcard);">
                                <summary style="padding: 1rem; cursor: pointer; color: var(--sentiment-negative); font-weight: 600; display:flex; align-items:center; gap:0.5rem;">
                                    <i data-lucide="chevron-down" style="width:16px;height:16px;"></i> Show ${restDesc.length} More Risks
                                </summary>
                                <div style="padding: 0 1rem 1rem 1rem;">
                                    <ul class="clean-list negative" style="margin-top:0;">
                                        ${restDesc.map(d => `<li><i data-lucide="alert-triangle" style="width:18px;height:18px;"></i> <span style="color:var(--text-main)">${d}</span></li>`).join('')}
                                    </ul>
                                </div>
                              </details>`;
                }
                risksContent.innerHTML = rHtml;
            }
        } else {
            document.getElementById('risks-grouped-content').innerHTML = '<span style="color:var(--text-muted)">No key risks specified.</span>';
        }

        // 6. Sentiment Section (Overview tab)
        if (Object.keys(sent).length > 0 && (sent.score !== null || sent.gmp !== null)) {
            document.getElementById('sentiment-section-container').classList.remove('hidden');
            
            const score = sent.score !== null && sent.score !== undefined ? sent.score : 0;
            document.getElementById('sentiment-score-text').innerText = sent.score !== null && sent.score !== undefined ? score : '--';
            
            const lbl = sent.sentiment_label || 'Neutral';
            const labelEl = document.getElementById('sentiment-label');
            labelEl.innerText = lbl;
            
            let gaugeColor = '#f59e0b';
            if (lbl.toLowerCase().includes('positive')) {
                labelEl.style.borderColor = 'var(--sentiment-positive)'; labelEl.style.color = 'var(--sentiment-positive)'; gaugeColor = '#10b981';
            } else if (lbl.toLowerCase().includes('negative')) {
                labelEl.style.borderColor = 'var(--sentiment-negative)'; labelEl.style.color = 'var(--sentiment-negative)'; gaugeColor = '#ef4444';
            } else {
                labelEl.style.borderColor = 'var(--sentiment-neutral)'; labelEl.style.color = 'var(--sentiment-neutral)';
            }

            const ctxGauge = document.getElementById('sentimentGauge').getContext('2d');
            const maxScore = 5;
            const remainder = Math.max(0, maxScore - score);
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

            sentimentChartInstance = new Chart(ctxGauge, {
                type: 'doughnut',
                data: {
                    datasets: [{
                        data: [score, remainder],
                        backgroundColor: [gaugeColor, isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.05)'],
                        borderWidth: 0
                    }]
                },
                options: {
                    rotation: -90, circumference: 180, cutout: '75%', responsive: true, maintainAspectRatio: false,
                    animation: { duration: 800, easing: 'easeOutQuart' },
                    plugins: { tooltip: { enabled: false }, legend: { display: false } }
                }
            });

            document.getElementById('sentiment-gmp').innerText = sent.gmp !== null && sent.gmp !== undefined ? sent.gmp : '--';
            const sub = sent.subscription || {};
            document.getElementById('sentiment-sub-total').innerHTML = sub.total !== null && sub.total !== undefined ? `<strong style="color:var(--text-main)">${sub.total}</strong>` : '--';
            document.getElementById('sentiment-sub-qib').innerHTML = sub.qib !== null && sub.qib !== undefined ? `<strong style="color:var(--text-main)">${sub.qib}</strong>` : '--';
            document.getElementById('sentiment-sub-nii').innerHTML = sub.nii !== null && sub.nii !== undefined ? `<strong style="color:var(--text-main)">${sub.nii}</strong>` : '--';
            document.getElementById('sentiment-sub-retail').innerHTML = sub.retail !== null && sub.retail !== undefined ? `<strong style="color:var(--text-main)">${sub.retail}</strong>` : '--';
            
        } else {
            document.getElementById('sentiment-section-container').classList.add('hidden');
        }

        lucide.createIcons();

    } catch (err) {
        document.getElementById('dashboard-loader').classList.add('hidden');
        document.getElementById('dashboard-content').classList.remove('hidden');
        document.getElementById('ipo-title').innerText = "Error Loading Data";
        console.error(err);
    }
}

function parseNum(val) {
    if (!val || val === '-' || val === '—') return null;
    let cleaned = String(val).toLowerCase().replace(/[₹,\s]/g, "");
    
    let mult = 1;
    if (cleaned.includes("lakh")) mult = 0.01;
    else if (cleaned.includes("mn") || cleaned.includes("million")) mult = 0.1;
    else if (cleaned.includes("bn") || cleaned.includes("billion")) mult = 100;
    
    cleaned = cleaned.replace(/(cr|crore|lakhs?|mn|bn|million|billion|%|x)/gi, "");
    const parsed = parseFloat(cleaned);
    return isNaN(parsed) ? null : parsed * mult;
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

    const sortedFins = [...financials].sort((a,b) => {
        let yA = a.year ? parseInt(String(a.year).replace(/\D/g, '')) || 0 : 0;
        let yB = b.year ? parseInt(String(b.year).replace(/\D/g, '')) || 0 : 0;
        return yA - yB;
    });

    const years = sortedFins.map(f => f.year || 'Unknown');
    const revenues = sortedFins.map(f => parseNum(f.revenue));
    const pats = sortedFins.map(f => parseNum(f.pat));
    const ebitdaMargins = sortedFins.map(f => parseNum(f.ebitda_margin_pct));
    const patMargins = sortedFins.map(f => parseNum(f.pat_margin_pct));

    const colors = getChartColors();

    const ctxRev = document.getElementById('revenueChart').getContext('2d');
    revenueChartInstance = new Chart(ctxRev, {
        type: 'bar',
        data: {
            labels: years,
            datasets: [
                { label: 'Revenue', data: revenues, backgroundColor: '#3b82f6', borderRadius: 4 },
                { label: 'PAT', data: pats, backgroundColor: '#10b981', borderRadius: 4 }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            animation: { duration: 800, easing: 'easeOutQuart' },
            plugins: { legend: { labels: { color: colors.text } }, title: { display: true, text: 'Revenue vs PAT (₹ in Crores)', color: colors.title } },
            scales: {
                x: { ticks: { color: colors.text }, grid: { color: colors.grid } },
                y: { ticks: { color: colors.text }, grid: { color: colors.grid } }
            }
        }
    });

    const ctxMar = document.getElementById('marginChart').getContext('2d');
    marginChartInstance = new Chart(ctxMar, {
        type: 'line',
        data: {
            labels: years,
            datasets: [
                { label: 'EBITDA Margin %', data: ebitdaMargins, borderColor: '#f59e0b', tension: 0.4, fill: false },
                { label: 'PAT Margin %', data: patMargins, borderColor: '#10b981', tension: 0.4, fill: false }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            animation: { duration: 800, easing: 'easeOutQuart' },
            plugins: { legend: { labels: { color: colors.text } }, title: { display: true, text: 'Margin Trends (%)', color: colors.title } },
            scales: {
                x: { ticks: { color: colors.text }, grid: { color: colors.grid } },
                y: { ticks: { color: colors.text }, grid: { color: colors.grid } }
            }
        }
    });

    const reversedFins = [...sortedFins].reverse();
    const cols = ['Year', 'Revenue', 'EBITDA', 'EBITDA Margin %', 'PAT', 'PAT Margin %', 'EPS', 'CFO'];
    cols.forEach(c => {
        const th = document.createElement('th'); th.innerText = c; thead.appendChild(th);
    });

    reversedFins.forEach(f => {
        const tr = document.createElement('tr');
        const vals = [f.year, f.revenue, f.ebitda, f.ebitda_margin_pct, f.pat, f.pat_margin_pct, f.eps, f.cfo];
        vals.forEach(v => {
            const td = document.createElement('td'); 
            td.innerText = (v !== null && v !== undefined) ? v : '—'; 
            td.style.color = "var(--text-main)";
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function openChat() {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    const sidepanel = document.getElementById('chat-sidepanel');
    sidepanel.classList.remove('hidden');
    document.body.classList.add('chat-open');
    setTimeout(() => { sidepanel.classList.add('open'); }, 10);
}

function closeChat() {
    const sidepanel = document.getElementById('chat-sidepanel');
    sidepanel.classList.remove('open');
    document.body.classList.remove('chat-open');
    setTimeout(() => { sidepanel.classList.add('hidden'); }, 300);
}

function initChatResizer() {
    const resizer = document.getElementById('chat-resizer');
    let isResizing = false;

    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        document.body.classList.add('is-resizing');
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        // Calculate width from right edge of the screen
        const newWidth = document.body.clientWidth - e.clientX;
        // Constrain width between 300px and 60% of screen width
        const minWidth = 300;
        const maxWidth = document.body.clientWidth * 0.6;
        
        if (newWidth >= minWidth && newWidth <= maxWidth) {
            document.documentElement.style.setProperty('--chat-width', `${newWidth}px`);
        }
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            document.body.classList.remove('is-resizing');
        }
    });
}

function resetChatUI() {
    const chatHistoryEl = document.getElementById('chat-history');
    chatHistoryEl.innerHTML = `
        <div class="chat-message assistant">
            <p>Hello! I am Sou AI, your IPO intelligence agent. I've read the full RHP. What would you like to know?</p>
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

function parseMarkdown(text) {
    let html = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    html = html.replace(/^\+ (.*$)/gim, '<li>$1</li>');
    html = html.replace(/^\* (.*$)/gim, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/gims, match => `<ul style="margin: 0.5rem 0; padding-left: 1.2rem;">${match}</ul>`);
    html = html.replace(/<\/ul>\s*<ul.*?>/gim, '');
    html = html.replace(/\n/g, '<br>');
    return html;
}

async function sendChatMessage(message) {
    if (!currentIpoName) return;
    const chatHistoryEl = document.getElementById('chat-history');
    
    const userMsgDiv = document.createElement('div');
    userMsgDiv.className = 'chat-message user';
    userMsgDiv.innerHTML = `<p>${message.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>`;
    chatHistoryEl.appendChild(userMsgDiv);
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;

    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'chat-message assistant loading';
    
    const ragSteps = [
        "Embedding query into vector space...",
        "Querying vector database for RHP clauses...",
        "Retrieving relevant sections...",
        "Synthesizing RHP data via RAG...",
        "Generating accurate response..."
    ];
    let stepIdx = 0;
    
    loadingDiv.innerHTML = `
        <div style="display:flex; align-items:center; gap:0.5rem;">
            <dotlottie-wc src="https://lottie.host/e387e3d3-f579-4efe-ac58-635246a65792/NhKwb6f1LR.lottie" style="width: 24px; height: 24px" autoplay loop></dotlottie-wc>
            <span id="loading-text-span">${ragSteps[0]}</span>
        </div>
    `;
    chatHistoryEl.appendChild(loadingDiv);
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;

    const textInterval = setInterval(() => {
        stepIdx = (stepIdx + 1) % ragSteps.length;
        const span = document.getElementById('loading-text-span');
        if(span) span.innerText = ragSteps[stepIdx];
    }, 2000);

    try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ipo_name: currentIpoName, message: message, chat_history: currentChatHistory })
        });
        
        clearInterval(textInterval);
        
        if (!response.ok) throw new Error("Chat failed");
        const data = await response.json();
        const answer = data.answer || "Sorry, I couldn't understand that.";

        currentChatHistory.push({ role: 'user', content: message });
        currentChatHistory.push({ role: 'assistant', content: answer });

        chatHistoryEl.removeChild(loadingDiv);
        const assistantMsgDiv = document.createElement('div');
        assistantMsgDiv.className = 'chat-message assistant';
        assistantMsgDiv.innerHTML = `<p>${parseMarkdown(answer)}</p>`;
        chatHistoryEl.appendChild(assistantMsgDiv);
        chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
    } catch (err) {
        clearInterval(textInterval);
        if(chatHistoryEl.contains(loadingDiv)) chatHistoryEl.removeChild(loadingDiv);
        const errorDiv = document.createElement('div');
        errorDiv.className = 'chat-message assistant';
        errorDiv.innerHTML = `<p style="color:var(--sentiment-negative);">Error: ${err.message}</p>`;
        chatHistoryEl.appendChild(errorDiv);
        chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
    }
}
