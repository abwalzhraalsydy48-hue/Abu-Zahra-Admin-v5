package com.abuzahra.admin.model

import org.json.JSONObject

data class DeviceStatus(
    val deviceId: String,
    val online: Boolean,
    val batteryLevel: Int,
    val isCharging: Boolean,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val lastSeen: Long = System.currentTimeMillis()
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("device_id", deviceId)
            put("online", online)
            put("battery_level", batteryLevel)
            put("is_charging", isCharging)
            put("latitude", latitude)
            put("longitude", longitude)
            put("last_seen", lastSeen)
        }
    }
    
    companion object {
        fun fromJson(json: JSONObject): DeviceStatus {
            return DeviceStatus(
                deviceId = json.getString("device_id"),
                online = json.optBoolean("online", false),
                batteryLevel = json.optInt("battery_level", 0),
                isCharging = json.optBoolean("is_charging", false),
                latitude = if (json.has("latitude")) json.getDouble("latitude") else null,
                longitude = if (json.has("longitude")) json.getDouble("longitude") else null,
                lastSeen = json.optLong("last_seen", System.currentTimeMillis())
            )
        }
    }
}
