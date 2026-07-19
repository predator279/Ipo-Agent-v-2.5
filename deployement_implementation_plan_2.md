# 🏗️ Architecture Pivot & Final Fixes Plan (Option 1)

You have chosen **Option 1 (Change Data Source)**. This is a very clean choice because it means you do not need any third-party proxy API keys, and it will remain 100% free forever. We will bypass the NSE firewall entirely by scraping from a public aggregator.

Here is the plan to execute this pivot and fix the remaining deployment issues.

## 🛠️ The Action Plan (What we have to do)

### Phase 1: User Actions (Things you need to do)
> [!IMPORTANT]  
> You need to perform these steps in the Azure Portal and Qdrant Cloud.

1. **Set up Qdrant Cloud (Crucial for the AI Chatbot):**
   - Go to [cloud.qdrant.io](https://cloud.qdrant.io/) and create a free cluster.
   - Copy the **Cluster URL** and **API Key**.
   - Add both of these to your **GitHub Repository Secrets** as `QDRANT_URL` and `QDRANT_API_KEY`.
   - Add both of these to your **Azure Function App -> Environment Variables** (under Settings).
2. **Fix the Azure Function 404:**
   - Go to your Azure Function App -> Environment Variables.
   - Add a new variable: Name = `AzureWebJobsFeatureFlags`, Value = `EnableWorkerIndexing`.
   - *(Also double-check that `SUPABASE_URL` and `SUPABASE_KEY` are present here!)*
   - Click **Apply / Save**. Your Azure function will restart and the 404 error will disappear.
3. **Find your Real Azure URL:**
   - Note down the exact URL of your Azure Function App (e.g., `https://my-app-name.azurewebsites.net`).

### Phase 2: Agent Actions (Things I will do)
Once you approve this plan, I will make the following code changes:

#### [MODIFY] `ipo_fetcher.py`
I will rewrite the scraper to pull the list of IPOs (Current, Upcoming, Past) from an aggregator (e.g., IPOWatch.in or Chittorgarh) instead of `nseindia.com`. This will completely bypass the GitHub Actions IP ban.

#### [MODIFY] `static/script.js`
I will update the `API_BASE_URL` to point to your real Azure Function URL instead of the `supreme-ipo-api-123` placeholder.

#### [MODIFY] `.github/workflows/nightly_precache.yml`
I will add `USE_QDRANT: true` to the GitHub Action environment so it knows to push the embeddings to your new Qdrant Cloud cluster instead of the ephemeral local disk.

## Verification Plan
1. You will complete Phase 1 and provide me with your real Azure Function URL.
2. I will write the code and push it to GitHub.
3. You will re-run the Nightly Pre-cacher in GitHub Actions (it will now successfully bypass NSE and push to Qdrant Cloud).
4. We will check the live website to see the IPOs load perfectly from Azure!
