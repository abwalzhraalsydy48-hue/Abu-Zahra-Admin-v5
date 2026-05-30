package com.abuzahra.admin.utils

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.os.Build
import androidx.core.app.NotificationCompat
import com.abuzahra.admin.R

object NotificationHelper {
    
    private const val CHANNEL_ID_DEFAULT = "default_channel"
    private const val CHANNEL_ID_SERVICE = "service_channel"
    
    fun createNotificationChannels(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            
            val defaultChannel = NotificationChannel(
                CHANNEL_ID_DEFAULT,
                "Default",
                NotificationManager.IMPORTANCE_DEFAULT
            )
            
            val serviceChannel = NotificationChannel(
                CHANNEL_ID_SERVICE,
                "Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                setShowBadge(false)
            }
            
            notificationManager.createNotificationChannels(listOf(defaultChannel, serviceChannel))
        }
    }
    
    fun createServiceNotification(
        context: Context,
        title: String,
        content: String,
        pendingIntent: PendingIntent
    ): Notification {
        return NotificationCompat.Builder(context, CHANNEL_ID_SERVICE)
            .setContentTitle(title)
            .setContentText(content)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }
    
    fun showNotification(
        context: Context,
        id: Int,
        title: String,
        content: String,
        pendingIntent: PendingIntent? = null
    ) {
        val builder = NotificationCompat.Builder(context, CHANNEL_ID_DEFAULT)
            .setContentTitle(title)
            .setContentText(content)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
        
        pendingIntent?.let {
            builder.setContentIntent(it)
        }
        
        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.notify(id, builder.build())
    }
}
