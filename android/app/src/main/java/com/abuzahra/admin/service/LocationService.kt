package com.abuzahra.admin.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.location.Location
import android.os.Build
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import com.abuzahra.admin.App
import com.abuzahra.admin.MainActivity
import com.abuzahra.admin.R
import com.abuzahra.admin.network.ApiService
import com.abuzahra.admin.utils.DeviceInfo
import com.google.android.gms.location.*
import kotlinx.coroutines.*
import org.json.JSONObject

class LocationService : Service() {
    
    companion object {
        @Volatile
        private var instance: LocationService? = null
        
        fun getInstance(): LocationService? = instance
    }
    
    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private lateinit var fusedLocationClient: FusedLocationProviderClient
    private lateinit var locationCallback: LocationCallback
    private var currentLocation: Location? = null
    private lateinit var apiService: ApiService
    
    override fun onCreate() {
        super.onCreate()
        instance = this
        apiService = ApiService.getInstance(this)
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this)
        
        setupLocationCallback()
        startForegroundNotification()
    }
    
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startLocationUpdates()
        return START_STICKY
    }
    
    override fun onBind(intent: Intent?): IBinder? = null
    
    private fun startForegroundNotification() {
        val pendingIntent = PendingIntent.getActivity(
            this,
            2,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )
        
        val notification = NotificationCompat.Builder(this, App.CHANNEL_ID_LOCATION)
            .setContentTitle("Location Service")
            .setContentText("Tracking location")
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
        
        startForeground(2, notification)
    }
    
    private fun setupLocationCallback() {
        locationCallback = object : LocationCallback() {
            override fun onLocationResult(locationResult: LocationResult) {
                locationResult.lastLocation?.let { location ->
                    currentLocation = location
                    sendLocationUpdate(location)
                }
            }
        }
    }
    
    private fun startLocationUpdates() {
        val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 10000)
            .setMinUpdateIntervalMillis(5000)
            .setWaitForAccurateLocation(true)
            .build()
        
        try {
            fusedLocationClient.requestLocationUpdates(
                locationRequest,
                locationCallback,
                Looper.getMainLooper()
            )
        } catch (e: SecurityException) {
            e.printStackTrace()
        }
    }
    
    private fun sendLocationUpdate(location: Location) {
        serviceScope.launch {
            val deviceId = DeviceInfo.getDeviceId(this@LocationService)
            apiService.updateLocation(deviceId, location.latitude, location.longitude)
        }
    }
    
    fun getCurrentLocation(): Location? = currentLocation
    
    override fun onDestroy() {
        super.onDestroy()
        fusedLocationClient.removeLocationUpdates(locationCallback)
        serviceScope.cancel()
        instance = null
    }
}
