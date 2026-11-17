package com.acme.android

/** Indirect UI component: ConversationActivity -> PassphraseRequiredActivity
 *  -> BaseActivity -> AppCompatActivity. */
class ConversationActivity : PassphraseRequiredActivity() {
    fun open() {
        // The chat list opens here.
    }
}
