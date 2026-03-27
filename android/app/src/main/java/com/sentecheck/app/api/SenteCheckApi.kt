package com.sentecheck.app.api

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST

data class SmsPayload(
    val telegram_id: Long,
    val raw_sms: String,
    val received_at: String,   // ISO-8601 UTC, e.g. "2026-03-27T14:32:00Z"
    val sim: String            // "MTN" or "Airtel"
)

data class WebhookResponse(
    val status: String,
    val action: String,
    val transaction_id: Int?
)

interface SenteCheckApi {
    @POST("webhook/sms")
    suspend fun forwardSms(
        @Header("X-Webhook-Secret") secret: String,
        @Body payload: SmsPayload
    ): Response<WebhookResponse>
}
