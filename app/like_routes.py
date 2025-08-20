from flask import Blueprint, request, jsonify
import asyncio
from datetime import datetime, timezone
import logging
import aiohttp
import requests

from .utils.protobuf_utils import encode_uid, decode_info, create_protobuf
from .utils.crypto_utils import encrypt_aes
from .token_manager import get_headers

logger = logging.getLogger(__name__)

# ✅ Must be defined before decorators
like_bp = Blueprint("like_bp", __name__)

_SERVERS = {}
_token_cache = None


# ------------------ HELPERS ------------------ #
async def async_post_request(url: str, data: bytes, token: str):
    try:
        headers = get_headers(token)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers, timeout=10) as resp:
                return await resp.read()
    except Exception as e:
        logger.error(f"Async request failed: {str(e)}")
        return None


def make_request(uid_enc: str, url: str, token: str):
    data = bytes.fromhex(uid_enc)
    headers = get_headers(token)
    try:
        response = requests.post(url, headers=headers, data=data, timeout=10)
        if response.status_code == 200:
            return decode_info(response.content)
        logger.warning(f"Request failed with status {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Request error: {str(e)}")
        return None


async def detect_player_region(uid: str):
    """Try all servers until UID is found."""
    for region_key, server_url in _SERVERS.items():
        tokens = _token_cache.get_tokens(region_key)
        if not tokens:
            continue

        info_url = f"{server_url}/GetPlayerPersonalShow"
        response = await async_post_request(info_url, bytes.fromhex(encode_uid(uid)), tokens[0])
        if response:
            player_info = decode_info(response)
            if player_info and player_info.AccountInfo.PlayerNickname:
                return region_key, player_info
    return None, None


async def send_likes(uid: str, region: str):
    """Send likes if tokens exist, otherwise return 0 likes."""
    tokens = _token_cache.get_tokens(region)
    if not tokens:
        logger.warning(f"No tokens available for region {region}, skipping like send.")
        return {"sent": 0, "added": 0}

    like_url = f"{_SERVERS[region]}/LikeProfile"
    encrypted = encrypt_aes(create_protobuf(uid, region))

    tasks = [async_post_request(like_url, bytes.fromhex(encrypted), token) for token in tokens]
    results = await asyncio.gather(*tasks)

    return {
        "sent": len(results),
        "added": sum(1 for r in results if r is not None)
    }


# ------------------ ROUTES ------------------ #
@like_bp.route("/like", methods=["GET"])
async def like_player():
    try:
        uid = request.args.get("uid")
        if not uid or not uid.isdigit():
            return jsonify({
                "error": "Invalid UID",
                "message": "Valid numeric UID required",
                "status": 400,
                "credits": "https://t.me/nopethug"
            }), 400

        # Detect region
        region, player_info = await detect_player_region(uid)
        if not player_info:
            return jsonify({
                "error": "Player not found",
                "message": "Player not found on any server",
                "status": 404,
                "credits": "https://t.me/nopethug"
            }), 404

        before_likes = player_info.AccountInfo.Likes
        player_name = player_info.AccountInfo.PlayerNickname
        info_url = f"{_SERVERS[region]}/GetPlayerPersonalShow"

        # Try sending likes
        like_result = await send_likes(uid, region)

        # If no tokens, we just return 0 added likes
        if like_result["sent"] == 0:
            after_likes = before_likes
        else:
            current_tokens = _token_cache.get_tokens(region)
            if not current_tokens:
                after_likes = before_likes
            else:
                new_info = make_request(encode_uid(uid), info_url, current_tokens[0])
                after_likes = new_info.AccountInfo.Likes if new_info else before_likes

        return jsonify({
            "player": player_name,
            "uid": uid,
            "likes_added": after_likes - before_likes,
            "likes_before": before_likes,
            "likes_after": after_likes,
            "server_used": region,
            "status": 1 if after_likes > before_likes else 2,
            "credits": "https://t.me/nopethug"
        })

    except Exception as e:
        logger.error(f"Like error for UID {uid}: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Internal server error",
            "message": str(e),
            "status": 500,
            "credits": "https://t.me/nopethug"
        }), 500


@like_bp.route("/health-check", methods=["GET"])
def health_check():
    try:
        token_status = {
            server: len(_token_cache.get_tokens(server)) > 0
            for server in _SERVERS
        }

        return jsonify({
            "status": "healthy" if all(token_status.values()) else "degraded",
            "servers": token_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "credits": "https://t.me/nopethug"
        })
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "credits": "https://t.me/nopethug"
        }), 500


@like_bp.route("/", methods=["GET"])
async def root_home():
    return jsonify({
        "message": "Api free fire like",
        "credits": "https://t.me/nopethug",
    })


# ------------------ INITIALIZER ------------------ #
def initialize_routes(app_instance, servers_config, token_cache_instance):
    global _SERVERS, _token_cache
    _SERVERS = servers_config
    _token_cache = token_cache_instance
    app_instance.register_blueprint(like_bp)
