package com.sentecheck.app

import android.content.Context
import android.util.Log
import com.sentecheck.app.api.SenteCheckApi
import com.sentecheck.app.api.SmsPayload
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.time.Instant

private const val TAG = "SmsForwarder"
private const val PREF_NAME = "sentecheck_prefs"
private const val KEY_TELEGRAM_ID = "telegram_id"
private const val KEY_WEBHOOK_SECRET = "webhook_secret"
private const val KEY_API_URL = "api_url"

/**
 * SmsForwarder — POSTs a mobile money SMS to the SenteCheck backend.
 *
 * Design rules (from CLAUDE.md):
 * - Retry once on network failure, then fail silently.
 * - Never show errors to the user — log to Logcat only.
 * - Never forward an SMS that did not pass MobileMoneyFilter.
 */
object SmsForwarder {

    private fun buildApi(apiUrl: String): SenteCheckApi {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }
        val client = OkHttpClient.Builder()
            .addInterceptor(logging)
            .build()
        return Retrofit.Builder()
            .baseUrl(apiUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(SenteCheckApi::class.java)
    }

    /**
     * Forwards [body] to the backend, associating it with the Telegram user
     * stored in SharedPreferences.  Runs on the IO dispatcher; caller does
     * not need to launch a coroutine.
     */
    fun forward(context: Context, body: String, simSlot: Int) {
        val prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        val telegramId = prefs.getLong(KEY_TELEGRAM_ID, -1L)
        val webhookSecret = prefs.getString(KEY_WEBHOOK_SECRET, "") ?: ""
        val apiUrl = prefs.getString(KEY_API_URL, BuildConfig.API_BASE_URL) ?: BuildConfig.API_BASE_URL

        if (telegramId < 0 || webhookSecret.isBlank()) {
            Log.d(TAG, "Not configured — skipping forward")
            return
        }

        val sim = if (simSlot == 1) "Airtel" else "MTN"
        val payload = SmsPayload(
            telegram_id = telegramId,
            raw_sms = body,
            received_at = Instant.now().toString(),
            sim = sim
        )

        CoroutineScope(Dispatchers.IO).launch {
            forwardWithRetry(buildApi(apiUrl), webhookSecret, payload)
        }
    }

    private suspend fun forwardWithRetry(
        api: SenteCheckApi,
        secret: String,
        payload: SmsPayload,
        attempts: Int = 2
    ) {
        repeat(attempts) { attempt ->
            try {
                val response = api.forwardSms(secret, payload)
                if (response.isSuccessful) {
                    Log.d(TAG, "Forwarded SMS — action: ${response.body()?.action}")
                    return
                } else {
                    Log.w(TAG, "Backend returned ${response.code()} on attempt ${attempt + 1}")
                }
            } catch (e: Exception) {
                Log.w(TAG, "Network error on attempt ${attempt + 1}: ${e.message}")
            }
        }
        // All attempts exhausted — fail silently, never surface to user
        Log.e(TAG, "Failed to forward SMS after $attempts attempts — giving up")
    }
}
