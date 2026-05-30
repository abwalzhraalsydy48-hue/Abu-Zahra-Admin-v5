package com.abuzahra.admin.utils

import android.annotation.SuppressLint
import android.content.Context
import android.location.LocationManager
import android.net.wifi.WifiManager
import android.os.Build
import android.provider.Settings
import android.telephony.TelephonyManager
import org.json.JSONObject
import java.util.*

object DeviceInfo {
    
    @SuppressLint("HardwareIds", "MissingPermission")
    fun getDeviceId(context: Context): String {
        val prefs = context.getSharedPreferences("abuzahra_prefs", Context.MODE_PRIVATE)
        var deviceId = prefs.getString("device_id", null)
        
        if (deviceId == null) {
            deviceId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
                ?: UUID.randomUUID().toString()
            prefs.edit().putString("device_id", deviceId).apply()
        }
        
        return deviceId
    }
    
    fun getDeviceInfo(context: Context): JSONObject {
        return JSONObject().apply {
            put("manufacturer", Build.MANUFACTURER)
            put("brand", Build.BRAND)
            put("model", Build.MODEL)
            put("device", Build.DEVICE)
            put("product", Build.PRODUCT)
            put("android_version", Build.VERSION.RELEASE)
            put("sdk_version", Build.VERSION.SDK_INT)
            put("build_id", Build.ID)
            put("fingerprint", Build.FINGERPRINT)
            put("board", Build.BOARD)
            put("hardware", Build.HARDWARE)
            put("serial", getSerialNumber())
            put("imei", getIMEI(context))
            put("phone_number", getPhoneNumber(context))
            put("sim_serial", getSimSerial(context))
            put("carrier", getCarrier(context))
            put("country", getCountry(context))
            put("language", Locale.getDefault().language)
            put("timezone", TimeZone.getDefault().id)
            put("wifi_mac", getWifiMac(context))
        }
    }
    
    @SuppressLint("HardwareIds", "MissingPermission")
    private fun getSerialNumber(): String {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                Build.getSerial()
            } else {
                Build.SERIAL
            }
        } catch (e: Exception) {
            "unknown"
        }
    }
    
    @SuppressLint("HardwareIds", "MissingPermission")
    private fun getIMEI(context: Context): String {
        return try {
            val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                telephonyManager.imei ?: "unknown"
            } else {
                telephonyManager.deviceId ?: "unknown"
            }
        } catch (e: Exception) {
            "unknown"
        }
    }
    
    @SuppressLint("HardwareIds", "MissingPermission")
    private fun getPhoneNumber(context: Context): String {
        return try {
            val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
            telephonyManager.line1Number ?: "unknown"
        } catch (e: Exception) {
            "unknown"
        }
    }
    
    @SuppressLint("HardwareIds", "MissingPermission")
    private fun getSimSerial(context: Context): String {
        return try {
            val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
            telephonyManager.simSerialNumber ?: "unknown"
        } catch (e: Exception) {
            "unknown"
        }
    }
    
    private fun getCarrier(context: Context): String {
        return try {
            val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
            telephonyManager.networkOperatorName ?: "unknown"
        } catch (e: Exception) {
            "unknown"
        }
    }
    
    private fun getCountry(context: Context): String {
        return try {
            val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
            telephonyManager.networkCountryIso ?: Locale.getDefault().country
        } catch (e: Exception) {
            Locale.getDefault().country
        }
    }
    
    @SuppressLint("HardwareIds")
    private fun getWifiMac(context: Context): String {
        return try {
            val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            wifiManager.connectionInfo.macAddress ?: "unknown"
        } catch (e: Exception) {
            "unknown"
        }
    }
    
    fun getBatteryLevel(context: Context): Int {
        val batteryIntent = context.registerReceiver(null, android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED))
        val level = batteryIntent?.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = batteryIntent?.getIntExtra(android.os.BatteryManager.EXTRA_SCALE, -1) ?: -1
        
        return if (level != -1 && scale != -1) {
            (level * 100 / scale.toFloat()).toInt()
        } else {
            -1
        }
    }
    
    fun isCharging(context: Context): Boolean {
        val batteryIntent = context.registerReceiver(null, android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED))
        val status = batteryIntent?.getIntExtra(android.os.BatteryManager.EXTRA_STATUS, -1) ?: -1
        return status == android.os.BatteryManager.BATTERY_STATUS_CHARGING ||
               status == android.os.BatteryManager.BATTERY_STATUS_FULL
    }
    
    fun getStorageInfo(): JSONObject {
        return JSONObject().apply {
            val internalPath = android.os.Environment.getDataDirectory()
            val stat = android.os.StatFs(internalPath.path)
            
            val blockSize = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR2) {
                stat.blockSizeLong
            } else {
                stat.blockSize.toLong()
            }
            
            val totalBlocks = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR2) {
                stat.blockCountLong
            } else {
                stat.blockCount.toLong()
            }
            
            val availableBlocks = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR2) {
                stat.availableBlocksLong
            } else {
                stat.availableBlocks.toLong()
            }
            
            val totalStorage = totalBlocks * blockSize
            val availableStorage = availableBlocks * blockSize
            
            put("total_storage", totalStorage)
            put("available_storage", availableStorage)
            put("used_storage", totalStorage - availableStorage)
        }
    }
    
    fun getNetworkInfo(context: Context): JSONObject {
        return JSONObject().apply {
            val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
            val activeNetwork = connectivityManager.activeNetworkInfo
            
            put("connected", activeNetwork?.isConnectedOrConnecting ?: false)
            put("type", activeNetwork?.typeName ?: "none")
            put("subtype", activeNetwork?.subtypeName ?: "none")
            put("roaming", activeNetwork?.isRoaming ?: false)
        }
    }
}
