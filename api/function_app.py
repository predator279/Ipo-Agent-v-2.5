import azure.functions as func
import logging
import json
import os
from supabase import create_client, Client

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

def get_supabase() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

@app.route(route="ipos")
def get_ipos(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request for IPOs.')
    try:
        sb = get_supabase()
        # Fetch cached IPO profiles
        response = sb.table("ipo_profiles").select("ipo_name, symbol, updated_at").execute()
        return func.HttpResponse(json.dumps(response.data), mimetype="application/json")
    except Exception as e:
        logging.error(f"Error fetching IPOs: {e}")
        return func.HttpResponse("Error fetching IPOs", status_code=500)

@app.route(route="ipos/{ipo_name}")
def get_ipo_profile(req: func.HttpRequest) -> func.HttpResponse:
    ipo_name = req.route_params.get('ipo_name')
    logging.info(f'Fetching profile for {ipo_name}')
    try:
        sb = get_supabase()
        response = sb.table("ipo_profiles").select("profile_json").eq("ipo_name", ipo_name).execute()
        if response.data:
            return func.HttpResponse(json.dumps(response.data[0]['profile_json']), mimetype="application/json")
        else:
            return func.HttpResponse("Not Found", status_code=404)
    except Exception as e:
        logging.error(f"Error fetching IPO profile: {e}")
        return func.HttpResponse("Error", status_code=500)
