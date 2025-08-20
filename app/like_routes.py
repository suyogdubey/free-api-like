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

        # Try to detect the player's region + profile
        region, player_info = await detect_player_region(uid)

        # If detection failed, return safe response instead of hard 404
        if not player_info:
            return jsonify({
                "uid": uid,
                "server_used": region if region else "UNKNOWN",
                "player": None,
                "likes_added": 0,
                "likes_before": 0,
                "likes_after": 0,
                "status": 0,
                "message": "No valid tokens or player not found",
                "credits": "https://t.me/nopethug"
            }), 200

        # We found player info, continue normal flow
        before_likes = player_info.AccountInfo.Likes
        player_name = player_info.AccountInfo.PlayerNickname
        info_url = f"{_SERVERS[region]}/GetPlayerPersonalShow"

        # Try to send likes
        await send_likes(uid, region)

        # Check if we have any tokens left to verify likes
        current_tokens = _token_cache.get_tokens(region)
        if not current_tokens:
            logger.error(f"No tokens available for {region} to verify likes after sending.")
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
