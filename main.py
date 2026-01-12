from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import xmltodict
import asyncio
import os
from dotenv import load_dotenv

# Load environment variables from 'env' file (local development only)
# In production, cloud providers will use environment variables configured in their dashboards
load_dotenv("env", override=False)

app = FastAPI(title="DELUXY - BGG Proxy API")

# CORS: in production you can restrict to your Shopify domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get BGG token from environment variable (protected in backend)
BGG_TOKEN = os.getenv("BGG_TOKEN")

if not BGG_TOKEN:
    raise ValueError(
        "BGG_TOKEN is not configured. Please set the BGG_TOKEN environment variable in the 'env' file."
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/get-bgg-games")
async def get_bgg_games(
    username: str = Query(..., description="BGG username")
):
    """
    Get games from BGG
    - Args:
        - username: BGG username
    - Returns:
        - list of games
    """
    if not username:
        raise HTTPException(status_code=400, detail="username is required")

    url = f"https://boardgamegeek.com/xmlapi2/collection?username={username}&own=1&subtype=boardgame&excludesubtype=boardgameexpansion"
    
    headers = {
        "Authorization": f"Bearer {BGG_TOKEN}"
    }
    
    # According to BGG documentation:
    # - Status 202: request is queued, need to retry
    # - Status 500/503: rate limiting, wait 5 seconds and retry
    max_retries = 5
    retry_delay = 5  # seconds (recommended by BGG for rate limiting)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(max_retries):
            try:
                resp = await client.get(url, headers=headers)
                
                # Status 202: BGG is processing the request, retry
                if resp.status_code == 202:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        raise HTTPException(
                            status_code=202,
                            detail="BGG is processing the collection. Please try again in a few moments."
                        )
                
                # Status 500/503: rate limiting, wait and retry
                if resp.status_code in (500, 503):
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        raise HTTPException(
                            status_code=503,
                            detail="BGG is very busy. Please try again later."
                        )
                
                # Other HTTP errors
                if resp.status_code != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"BGG returned HTTP error {resp.status_code}: {resp.text[:200]}"
                    )
                
                # If we reach here, we have a 200 response
                break
                
            except httpx.TimeoutException as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                raise HTTPException(status_code=504, detail=f"Timeout contacting BGG after {max_retries} attempts: {e}")
            except httpx.HTTPError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                raise HTTPException(status_code=502, detail=f"Error contacting BGG after {max_retries} attempts: {str(e)}")
        else:
            # If we exit the loop without break, all attempts failed
            raise HTTPException(
                status_code=503,
                detail=f"Could not retrieve collection after {max_retries} attempts"
            )

    xml = resp.text

    # Parse XML → dict
    try:
        data = xmltodict.parse(xml)
    except Exception as e:
        raise HTTPException(
            status_code=502, 
            detail=f"Could not parse BGG XML response: {str(e)}. Received response: {xml[:500]}"
        )

    # When BGG is still preparing the collection, it returns a <message>
    if "message" in data:
        message = data["message"].get("#text") if isinstance(data["message"], dict) else data["message"]
        return {"status": "processing", "message": message}

    items = data.get("items", {}).get("item", [])
    if isinstance(items, dict):
        items = [items]

    result = []
    for game in items:
        # Extract objectid
        objectid = game.get("@objectid")
        
        # Extract name - can be a dict, a list, or direct text
        name_data = game.get("name")
        name = None
        
        if isinstance(name_data, list):
            # If it's a list, find the one with sortindex="1" or take the first one
            for n in name_data:
                if isinstance(n, dict):
                    if n.get("@sortindex") == "1" or n.get("@sortindex") == 1:
                        name = n.get("#text", n.get("@value", ""))
                        break
            # If we didn't find sortindex="1", take the first one
            if name is None and name_data:
                first_name = name_data[0]
                if isinstance(first_name, dict):
                    name = first_name.get("#text", first_name.get("@value", ""))
                else:
                    name = str(first_name)
        elif isinstance(name_data, dict):
            # If it's a dict, extract the text
            name = name_data.get("#text", name_data.get("@value", ""))
        else:
            # If it's direct text
            name = str(name_data) if name_data else None
        
        result.append({
            "objectid": objectid,
            "name": name
        })

    return {"status": "ok", "count": len(result), "items": result}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


