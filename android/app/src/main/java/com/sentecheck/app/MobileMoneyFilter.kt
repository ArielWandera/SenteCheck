package com.sentecheck.app

/**
 * MobileMoneyFilter — determines whether an incoming SMS is a mobile money
 * notification that should be forwarded to the SenteCheck backend.
 *
 * We match on content keywords rather than sender IDs because MTN and Airtel
 * Uganda use multiple short codes and the set changes over time.  Personal
 * messages, WhatsApp notifications, and any SMS that does not contain at
 * least one of the keywords below will never leave the device.
 */
object MobileMoneyFilter {

    private val KEYWORDS = listOf(
        "UGX",
        "MTN Mobile Money",
        "Airtel Money",
        "new balance",
        "transaction",
        "you have sent",
        "you have received",
        "your withdrawal"
    )

    /**
     * Returns true only if [body] contains at least one mobile money keyword.
     * Comparison is case-insensitive.
     */
    fun isMobileMoneySms(body: String): Boolean =
        KEYWORDS.any { keyword -> body.contains(keyword, ignoreCase = true) }
}
