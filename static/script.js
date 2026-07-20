// Azure Function App URL (Backend API)
const API_BASE_URL = 'https://supreme-ipo-api-123.azurewebsites.net/api';

let currentIpoName = null;
let currentChatHistory = [];
let revenueChartInstance = null;
let marginChartInstance = null;
let objectsChartInstance = null;
let sentimentChartInstance = null;

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

        // Reset Risks and New Sections
        document.getElementById('key-metrics-section-container').classList.add('hidden');
        document.getElementById('peer-comparison-section-container').classList.add('hidden');
        document.getElementById('objects-issue-section-container').classList.add('hidden');
        document.getElementById('management-section-container').classList.add('hidden');
        document.getElementById('sentiment-section-container').classList.add('hidden');
        document.getElementById('risks-section-container').classList.add('hidden');
        document.getElementById('risks-content').innerHTML = 'Loading...';

        if (objectsChartInstance) { objectsChartInstance.destroy(); objectsChartInstance = null; }
        if (sentimentChartInstance) { sentimentChartInstance.destroy(); sentimentChartInstance = null; }

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
        let financialsData = fin.yearly_financials || data.financials;
        if (!financialsData && data.financial_summary && data.financial_summary.revenue_fy_latest) {
            financialsData = [{
                year: 'Latest',
                revenue: data.financial_summary.revenue_fy_latest,
                pat: data.financial_summary.profit_after_tax_fy_latest,
                ebitda: null, ebitda_margin_pct: null, pat_margin_pct: null, eps: null, cfo: null
            }];
        }
        if (financialsData && Array.isArray(financialsData)) {
            financialsData = financialsData.map(f => ({
                ...f,
                ebitda_margin_pct: f.ebitda_margin_pct !== undefined ? f.ebitda_margin_pct : f.ebitda_margin,
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
            
            // Balance Sheet
            if (bsArr.length) {
                document.getElementById('metrics-col-bs').classList.remove('hidden');
                document.getElementById('metrics-bs-list').innerHTML = bsArr.map(x => `<li><strong>${x.label}:</strong> ${x.value}</li>`).join('');
            } else {
                document.getElementById('metrics-col-bs').classList.add('hidden');
            }
            
            // Return Ratios & Valuation Multiples
            if (rrArr.length || vmArr.length) {
                document.getElementById('metrics-col-ratios').classList.remove('hidden');
                if (rrArr.length) {
                    document.getElementById('metrics-ratios-sub').classList.remove('hidden');
                    document.getElementById('metrics-ratios-list').innerHTML = rrArr.map(x => `<li><strong>${x.label}:</strong> ${x.value}</li>`).join('');
                } else {
                    document.getElementById('metrics-ratios-sub').classList.add('hidden');
                }
                if (vmArr.length) {
                    document.getElementById('metrics-valuation-sub').classList.remove('hidden');
                    document.getElementById('metrics-valuation-list').innerHTML = vmArr.map(x => `<li><strong>${x.label}:</strong> ${x.value}</li>`).join('');
                } else {
                    document.getElementById('metrics-valuation-sub').classList.add('hidden');
                }
            } else {
                document.getElementById('metrics-col-ratios').classList.add('hidden');
            }
            
            // Sector KPIs
            if (skArr.length) {
                document.getElementById('metrics-col-kpis').classList.remove('hidden');
                document.getElementById('metrics-kpis-list').innerHTML = skArr.map(x => `<li><strong>${x.label}:</strong> ${x.value}</li>`).join('');
            } else {
                document.getElementById('metrics-col-kpis').classList.add('hidden');
            }
        }

        // 2. Peer Comparison
        const peers = data.peer_comparison || [];
        if (peers.length > 0) {
            document.getElementById('peer-comparison-section-container').classList.remove('hidden');
            document.getElementById('peer-tbody').innerHTML = peers.map(p => `
                <tr>
                    <td>${p.name || '—'}</td>
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
            
            // Breakdown Chart
            const chartData = objBreakdown.filter(x => x.amount !== null && x.amount !== undefined);
            if (chartData.length > 0) {
                document.getElementById('objects-chart-container').classList.remove('hidden');
                document.getElementById('objects-no-chart').classList.add('hidden');
                const ctxObj = document.getElementById('objectsChart').getContext('2d');
                objectsChartInstance = new Chart(ctxObj, {
                    type: 'doughnut',
                    data: {
                        labels: chartData.map(x => x.purpose || 'Unknown'),
                        datasets: [{
                            data: chartData.map(x => x.amount),
                            backgroundColor: ['#3b82f6', '#10b981', '#fbbf24', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4'],
                            borderWidth: 0
                        }]
                    },
                    options: {
                        responsive: true, maintainAspectRatio: false,
                        plugins: { legend: { position: 'right', labels: { color: '#94a3b8' } } }
                    }
                });
            } else {
                document.getElementById('objects-chart-container').classList.add('hidden');
                document.getElementById('objects-no-chart').classList.remove('hidden');
            }
            
            // Categories List
            if (objCategories.length > 0) {
                document.getElementById('objects-categories-list').innerHTML = objCategories.map(c => `<span class="badge">${c}</span>`).join('');
            } else {
                document.getElementById('objects-categories-list').innerHTML = '<span style="color:var(--text-muted)">No categories specified.</span>';
            }
        }

        // 4. Management & Promoters
        const mgt = data.management || {};
        const keyMgt = mgt.key_management || [];
        const promoters = mgt.promoters || [];
        const litigations = mgt.litigations || {};
        
        if (keyMgt.length || promoters.length || litigations.status_summary || litigations.details) {
            document.getElementById('management-section-container').classList.remove('hidden');
            
            if (keyMgt.length) {
                document.getElementById('mgmt-key-col').classList.remove('hidden');
                document.getElementById('mgmt-key-list').innerHTML = keyMgt.map(m => `<span class="badge" style="display:block; text-align:left; border-color:var(--border); color:var(--text-main); background:rgba(255,255,255,0.02)">👤 ${m.name} — ${m.role}</span>`).join('');
            } else {
                document.getElementById('mgmt-key-col').classList.add('hidden');
            }
            
            if (promoters.length) {
                document.getElementById('mgmt-promoters-col').classList.remove('hidden');
                document.getElementById('mgmt-promoters-list').innerHTML = promoters.map(p => {
                    let typeStr = p.type ? ` (${p.type})` : '';
                    return `<span class="badge" style="display:block; text-align:left; border-color:var(--border); color:var(--text-main); background:rgba(255,255,255,0.02)">🏢 ${p.name}${typeStr}</span>`;
                }).join('');
            } else {
                document.getElementById('mgmt-promoters-col').classList.add('hidden');
            }
            
            if (litigations.status_summary || litigations.details) {
                document.getElementById('mgmt-litigations').classList.remove('hidden');
                let litHtml = '<strong>⚖️ Litigations:</strong> ';
                if (litigations.status_summary) litHtml += litigations.status_summary + ' ';
                if (litigations.details) litHtml += `<span style="color:var(--text-muted)">${litigations.details}</span>`;
                document.getElementById('mgmt-litigations').innerHTML = litHtml;
            } else {
                document.getElementById('mgmt-litigations').classList.add('hidden');
            }
        }

        // 5. Key Risks
        const risksArr = data.risk_factors || data.key_risks || [];
        if (risksArr && Array.isArray(risksArr) && risksArr.length > 0) {
            document.getElementById('risks-section-container').classList.remove('hidden');
            
            const risksContent = document.getElementById('risks-content');
            if (typeof risksArr[0] === 'object' && risksArr[0].category) {
                // Group by category
                const groups = {};
                risksArr.forEach(r => {
                    const c = r.category || 'Other Risks';
                    if (!groups[c]) groups[c] = [];
                    groups[c].push(r.description);
                });
                
                let risksHtml = '';
                for (const [cat, descs] of Object.entries(groups)) {
                    risksHtml += `
                        <div class="risk-category">
                            <h4 style="margin: 0 0 0.5rem 0; color: var(--text-main);">${cat}</h4>
                            <ul class="styled-list negative">
                                ${descs.map(d => `<li>${d}</li>`).join('')}
                            </ul>
                        </div>
                    `;
                }
                risksContent.innerHTML = risksHtml;
            } else {
                // Legacy format (flat strings)
                document.getElementById('risks-content').innerHTML = `<ul class="styled-list negative">${risksArr.map(r => `<li>${r}</li>`).join('')}</ul>`;
            }
        } else {
            document.getElementById('risks-section-container').classList.add('hidden');
        }

        // 6. Market Sentiment Analysis
        const sent = data.sentiment || {};
        if (Object.keys(sent).length > 0 && (sent.score !== null || sent.gmp !== null || (sent.summary && sent.summary.length))) {
            document.getElementById('sentiment-section-container').classList.remove('hidden');
            
            // Gauge
            const score = sent.score !== null && sent.score !== undefined ? sent.score : 0;
            document.getElementById('sentiment-score-text').innerText = sent.score !== null && sent.score !== undefined ? score : '--';
            
            const lbl = sent.sentiment_label || 'Neutral';
            const labelEl = document.getElementById('sentiment-label');
            labelEl.innerText = lbl;
            if (lbl.toLowerCase().includes('positive')) {
                labelEl.style.borderColor = 'var(--sentiment-positive)';
                labelEl.style.color = 'var(--sentiment-positive)';
            } else if (lbl.toLowerCase().includes('negative')) {
                labelEl.style.borderColor = 'var(--sentiment-negative)';
                labelEl.style.color = 'var(--sentiment-negative)';
            } else {
                labelEl.style.borderColor = 'var(--sentiment-neutral)';
                labelEl.style.color = 'var(--sentiment-neutral)';
            }

            const ctxGauge = document.getElementById('sentimentGauge').getContext('2d');
            let gaugeColor = '#fbbf24';
            if (lbl.toLowerCase().includes('positive')) gaugeColor = '#10b981';
            if (lbl.toLowerCase().includes('negative')) gaugeColor = '#ef4444';

            const maxScore = 5;
            const remainder = Math.max(0, maxScore - score);

            sentimentChartInstance = new Chart(ctxGauge, {
                type: 'doughnut',
                data: {
                    datasets: [{
                        data: [score, remainder],
                        backgroundColor: [gaugeColor, 'rgba(255,255,255,0.1)'],
                        borderWidth: 0
                    }]
                },
                options: {
                    rotation: -90,
                    circumference: 180,
                    cutout: '75%',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { tooltip: { enabled: false }, legend: { display: false } }
                }
            });

            // Overview stats
            document.getElementById('sentiment-gmp').innerText = sent.gmp !== null && sent.gmp !== undefined ? sent.gmp : '--';
            const sub = sent.subscription || {};
            document.getElementById('sentiment-sub-total').innerText = sub.total !== null && sub.total !== undefined ? sub.total : '--';
            document.getElementById('sentiment-sub-qib').innerText = sub.qib !== null && sub.qib !== undefined ? sub.qib : '--';
            document.getElementById('sentiment-sub-nii').innerText = sub.nii !== null && sub.nii !== undefined ? sub.nii : '--';
            document.getElementById('sentiment-sub-retail').innerText = sub.retail !== null && sub.retail !== undefined ? sub.retail : '--';
            
            const sources = sent.sources_used || [];
            document.getElementById('sentiment-sources').innerText = sources.length ? sources.join(' · ') : '--';

            // Positives / Negatives
            const pos = sent.positives || [];
            if (pos.length) {
                document.getElementById('sentiment-positives-col').classList.remove('hidden');
                document.getElementById('sentiment-positives-list').innerHTML = pos.map(p => `<li>${p}</li>`).join('');
            } else {
                document.getElementById('sentiment-positives-col').classList.add('hidden');
            }

            const neg = sent.negatives || [];
            if (neg.length) {
                document.getElementById('sentiment-negatives-col').classList.remove('hidden');
                document.getElementById('sentiment-negatives-list').innerHTML = neg.map(n => `<li>${n}</li>`).join('');
            } else {
                document.getElementById('sentiment-negatives-col').classList.add('hidden');
            }

            // Summary
            const sum = sent.summary || [];
            if (sum.length) {
                document.getElementById('sentiment-summary-col').classList.remove('hidden');
                document.getElementById('sentiment-summary-list').innerHTML = sum.map(s => `<li>${s}</li>`).join('');
            } else {
                document.getElementById('sentiment-summary-col').classList.add('hidden');
            }

            // Articles
            const arts = sent.articles || [];
            if (arts.length) {
                document.getElementById('sentiment-articles-col').classList.remove('hidden');
                document.getElementById('sentiment-articles-list').innerHTML = arts.map(a => `<li><a href="${a.url}" target="_blank" style="color:var(--accent); text-decoration:none;">${a.title}</a> <br><span style="color:var(--text-muted); font-size: 0.8rem;">— ${a.source}</span></li>`).join('');
            } else {
                document.getElementById('sentiment-articles-col').classList.add('hidden');
            }

        } else {
            document.getElementById('sentiment-section-container').classList.add('hidden');
        }

    } catch (err) {
        document.getElementById('ipo-title').innerText = "Error Loading Data";
        document.getElementById('risks-section-container').classList.remove('hidden');
        document.getElementById('risks-content').innerHTML = `<div style="color:#ef4444; background:transparent; border:none; padding:1rem;">${err.message}</div>`;
    }
}

function parseNum(val) {
    if (!val || val === '-' || val === '—') return null;
    let cleaned = String(val).toLowerCase().replace(/[₹,\s]/g, "");
    
    // Normalize to Crores for the chart
    let mult = 1;
    if (cleaned.includes("lakh")) mult = 0.01;
    else if (cleaned.includes("mn") || cleaned.includes("million")) mult = 0.1;
    else if (cleaned.includes("bn") || cleaned.includes("billion")) mult = 100;
    
    // Strip all text
    cleaned = cleaned.replace(/(cr|crore|lakhs?|mn|bn|million|billion|%|x)/gi, "");
    
    const parsed = parseFloat(cleaned);
    return isNaN(parsed) ? null : parsed * mult;
}

// ── Chart.js Integration ──────────────────────────────────────────────
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
        let yA = a.year ? parseInt(String(a.year).replace(/\D/g, '')) || 0 : 0;
        let yB = b.year ? parseInt(String(b.year).replace(/\D/g, '')) || 0 : 0;
        return yA - yB;
    });

    const years = sortedFins.map(f => f.year || 'Unknown');
    const revenues = sortedFins.map(f => parseNum(f.revenue));
    const pats = sortedFins.map(f => parseNum(f.pat));
    const ebitdaMargins = sortedFins.map(f => parseNum(f.ebitda_margin_pct));
    const patMargins = sortedFins.map(f => parseNum(f.pat_margin_pct));

    // Chart 1: Revenue vs PAT
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
    const cols = ['Year', 'Revenue', 'EBITDA', 'EBITDA Margin %', 'PAT', 'PAT Margin %', 'EPS', 'CFO'];
    cols.forEach(c => {
        const th = document.createElement('th'); th.innerText = c; thead.appendChild(th);
    });

    reversedFins.forEach(f => {
        const tr = document.createElement('tr');
        const vals = [f.year, f.revenue, f.ebitda, f.ebitda_margin_pct, f.pat, f.pat_margin_pct, f.eps, f.cfo];
        vals.forEach(v => {
            const td = document.createElement('td'); td.innerText = (v !== null && v !== undefined) ? v : '—'; tr.appendChild(td);
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
