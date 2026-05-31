package com.abuzahra.admin.network

import android.content.Context
import android.util.Log
import com.abuzahra.admin.utils.DeviceInfo
import kotlinx.coroutines.*
import okhttp3.*
import okio.ByteString
import java.util.concurrent.TimeUnit

class WebSocketManager private constructor(private val context: Context) {
    
    companion object {
        @Volatile
        private var instance: WebSocketManager? = null
        
        fun getInstance(context: Context): WebSocketManager {
            return instance ?: synchronized(this) {
                instance ?: WebSocketManager(context.applicationContext).also { instance = it }
            }
        }
    }
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .pingInterval(25, TimeUnit.SECONDS)
        .build()
    
    private var webSocket: WebSocket? = null
    private var listener: WebSocketListener? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    
    private var reconnectAttempts = 0
    private val maxReconnectAttempts = 5
    private val reconnectDelay = 5000L
    
    fun connect(url: String, listener: WebSocketListener) {
        this.listener = listener
        val request = Request.Builder()
            .url(url)
            .build()
        
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d("WebSocketManager", "Connection opened")
                reconnectAttempts = 0
                listener.onOpen(webSocket, response)
            }
            
            override fun onMessage(webSocket: WebSocket, text: String) {
                listener.onMessage(webSocket, text)
            }
            
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                listener.onMessage(webSocket, bytes)
            }
            
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                listener.onClosing(webSocket, code, reason)
            }
            
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.d("WebSocketManager", "Connection closed")
                listener.onClosed(webSocket, code, reason)
                scheduleReconnect(url)
            }
            
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e("WebSocketManager", "Connection failure", t)
                listener.onFailure(webSocket, t, response)
                scheduleReconnect(url)
            }
        })
    }
    
    private fun scheduleReconnect(url: String) {
        if (reconnectAttempts < maxReconnectAttempts) {
            reconnectAttempts++
            scope.launch {
                delay(reconnectDelay * reconnectAttempts)
                Log.d("WebSocketManager", "Reconnecting... attempt $reconnectAttempts")
                connect(url, listener!!)
            }
        }
    }
    
    fun send(message: String): Boolean {
        return webSocket?.send(message) ?: false
    }
    
    fun send(bytes: ByteString): Boolean {
        return webSocket?.send(bytes) ?: false
    }
    
    fun disconnect() {
        webSocket?.close(1000, "Normal closure")
        webSocket = null
        scope.cancel()
    }
    
    fun isConnected(): Boolean = webSocket != null
}
