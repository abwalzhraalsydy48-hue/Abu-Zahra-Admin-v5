package com.abuzahra.admin.model

import org.json.JSONObject

data class Command(
    val id: String,
    val type: String,
    val params: JSONObject?,
    val timestamp: Long = System.currentTimeMillis()
) {
    companion object {
        fun fromJson(json: JSONObject): Command {
            return Command(
                id = json.getString("id"),
                type = json.getString("type"),
                params = json.optJSONObject("params"),
                timestamp = json.optLong("timestamp", System.currentTimeMillis())
            )
        }
    }
    
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("id", id)
            put("type", type)
            put("params", params)
            put("timestamp", timestamp)
        }
    }
}
