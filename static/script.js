// Azure Function App URL (Backend API)
const API_BASE_URL = 'https://supreme-ipo-api-123.azurewebsites.net/api';

document.addEventListener('DOMContentLoaded', () => {
    fetchIPOs();

    document.getElementById('back-btn').addEventListener('click', () => {
        document.getElementById('ipo-details-section').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');
    });
});

async function fetchIPOs() {
    try {
        const response = await fetch(`${API_BASE_URL}/ipos`);
        if (!response.ok) throw new Error("Backend API not responding");
        const data = await response.json();
        
        const listDiv = document.getElementById('ipo-list');
        listDiv.innerHTML = '';
        
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');

        if (!data || data.length === 0) {
            listDiv.innerHTML = '<p style="color: var(--text-muted)">No pre-cached IPOs found in database.</p>';
            return;
        }

        data.forEach(ipo => {
            const card = document.createElement('div');
            card.className = 'ipo-card';
            
            // Format date nicely if available
            let dateStr = ipo.updated_at ? new Date(ipo.updated_at).toLocaleDateString() : 'N/A';

            card.innerHTML = `
                <h3>${ipo.ipo_name}</h3>
                <p>Symbol: ${ipo.symbol || 'N/A'}</p>
                <p style="font-size: 0.8rem; margin-top: 0.5rem; opacity: 0.7;">Cached: ${dateStr}</p>
            `;
            card.onclick = () => fetchIPODetails(ipo.ipo_name);
            listDiv.appendChild(card);
        });
    } catch (err) {
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('ipo-list-section').classList.remove('hidden');
        document.getElementById('ipo-list').innerHTML = `<p style="color:#ef4444;">Failed to load IPOs: ${err.message}</p>`;
    }
}

async function fetchIPODetails(ipoName) {
    try {
        document.getElementById('ipo-list-section').classList.add('hidden');
        const detailsSection = document.getElementById('ipo-details-section');
        detailsSection.classList.remove('hidden');
        
        document.getElementById('ipo-title').innerText = ipoName;
        document.getElementById('ipo-content').innerHTML = "<i>Fetching AI analysis...</i>";
        
        const response = await fetch(`${API_BASE_URL}/ipos/${encodeURIComponent(ipoName)}`);
        if (!response.ok) throw new Error("Failed to load details");
        const data = await response.json();
        
        // Display pretty JSON for now
        document.getElementById('ipo-content').innerText = JSON.stringify(data, null, 2);
    } catch (err) {
        document.getElementById('ipo-content').innerHTML = `<p style="color:#ef4444;">Error: ${err.message}</p>`;
    }
}
