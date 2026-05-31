package com.abuzahra.admin.manager

import android.content.Context
import android.content.SharedPreferences

class PreferenceManager {
    
    companion object {
        private const val PREF_NAME = "abuzahra_prefs"
        private var instance: PreferenceManager? = null
        private lateinit var prefs: SharedPreferences
        
        const val KEY_DEVICE_ID = "device_id"
        const val KEY_REGISTERED = "registered"
        const val KEY_LAST_SYNC = "last_sync"
        
        fun init(context: Context) {
            prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
            instance = PreferenceManager()
        }
        
        fun getInstance(): PreferenceManager {
            return instance ?: throw IllegalStateException("PreferenceManager not initialized")
        }
    }
    
    fun putString(key: String, value: String) {
        prefs.edit().putString(key, value).apply()
    }
    
    fun getString(key: String, defaultValue: String = ""): String {
        return prefs.getString(key, defaultValue) ?: defaultValue
    }
    
    fun putInt(key: String, value: Int) {
        prefs.edit().putInt(key, value).apply()
    }
    
    fun getInt(key: String, defaultValue: Int = 0): Int {
        return prefs.getInt(key, defaultValue)
    }
    
    fun putBoolean(key: String, value: Boolean) {
        prefs.edit().putBoolean(key, value).apply()
    }
    
    fun getBoolean(key: String, defaultValue: Boolean = false): Boolean {
        return prefs.getBoolean(key, defaultValue)
    }
    
    fun putLong(key: String, value: Long) {
        prefs.edit().putLong(key, value).apply()
    }
    
    fun getLong(key: String, defaultValue: Long = 0L): Long {
        return prefs.getLong(key, defaultValue)
    }
    
    fun remove(key: String) {
        prefs.edit().remove(key).apply()
    }
    
    fun clear() {
        prefs.edit().clear().apply()
    }
    
    // Specific preferences
    fun setDeviceId(deviceId: String) {
        putString(KEY_DEVICE_ID, deviceId)
    }
    
    fun getDeviceId(): String {
        return getString(KEY_DEVICE_ID)
    }
    
    fun setRegistered(registered: Boolean) {
        putBoolean(KEY_REGISTERED, registered)
    }
    
    fun isRegistered(): Boolean {
        return getBoolean(KEY_REGISTERED)
    }
    
    fun setLastSyncTime(time: Long) {
        putLong(KEY_LAST_SYNC, time)
    }
    
    fun getLastSyncTime(): Long {
        return getLong(KEY_LAST_SYNC)
    }
}
