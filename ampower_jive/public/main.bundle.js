/**
 * -----------------------------------------------------------------------------
 * AmPower Jive Chatbot Integration
 * -----------------------------------------------------------------------------
 * This script dynamically loads and initializes the n8n Chat UI for the 
 * AmPower Jive assistant. It fetches the chatbot configuration (webhook URL, 
 * session ID, instance endpoint, etc.) from the Frappe backend and embeds 
 * the chat interface into the page.
 *
 * The chatbot UI and initialization logic are based on the n8n Chat UI 
 * open-source library available at:
 * 👉 https://n8nchatui.com/
 *
 * Reference:
 * The code structure and Chatbot initialization options have been inspired 
 * and adapted from the official n8n Chat UI documentation and examples.
 * -----------------------------------------------------------------------------
 */


function initN8nChat() {
  frappe
    .call(
      "ampower_jive.ampower_jive.whitelist_functions.get_n8n_webhook_url.get_chat_bot_configuration"
    )
    .then((r) => {
      const webhookUrl = r.message.url;
      const sessionId = r.message.sid;
      const instanceEndPoint = r.message.instance_end_point || "";
      const activeJive = r.message.active;

      if (!activeJive) {
        return; // Exit if AmPower Jive is not active
      }
      if (!instanceEndPoint){
        return; // Exit if instance end point is not defined
      }

      // Dynamically create and append the module script tag for n8n chat UI
      const script = document.createElement("script");
      script.type = "module";
      script.defer = true;
      script.textContent = `
      import Chatbot from "https://cdn.n8nchatui.com/v1/embed.js";
      Chatbot.init({
        n8nChatUrl: "${webhookUrl}",
        metadata: {
          n8nchatui: {
            sessionId: "${sessionId}"
          },
          instanceEndPoint: "${instanceEndPoint}"
        },
        theme: {
          button: {
            backgroundColor: "#d4d4d4",
            right: 20,
            bottom: 20,
            size: 40,
            iconColor: "#373434",
            customIconSrc: "https://www.svgrepo.com/show/339963/chat-bot.svg",
            customIconSize: 67,
            customIconBorderRadius: 26,
            autoWindowOpen: {
              autoOpen: false,
              openDelay: 2
            },
            borderRadius: "rounded"
          },
          tooltip: {
            showTooltip: true,
            tooltipMessage: "Hi there! 👋, My self Jive. How can I assist you today?",
            tooltipBackgroundColor: "#f0f0f0",
            tooltipTextColor: "#1c1c1c",
            tooltipFontSize: 10
          },
          chatWindow: {
            borderRadiusStyle: "rounded",
            avatarBorderRadius: 19,
            messageBorderRadius: 25,
            showTitle: true,
            title: "AmPower Jive",
            titleAvatarSrc: "https://www.svgrepo.com/show/339963/chat-bot.svg",
            avatarSize: 30,
            welcomeMessage: "Hello! How may i help you.",
            errorMessage: "Oops! I am unable to find the information. Please add more information and I will try to help you!",
            backgroundColor: "#ede8ed",
            height: 600,
            width: 400,
            fontSize: 13,
            starterPrompts: [
              "I like to know about Recent created Sales Order?",
              "How to create purchase Invoice ?"
            ],
            starterPromptFontSize: 12,
            renderHTML: true,
            clearChatOnReload: false,
            showScrollbar: false,
            botMessage: {
              backgroundColor: "#98d3e7",
              textColor: "#0f0f0f",
              showAvatar: true,
              avatarSrc: "https://www.svgrepo.com/show/334455/bot.svg",
              showCopyToClipboardIcon: true
            },
            userMessage: {
              backgroundColor: "#fff6f3",
              textColor: "#050505",
              showAvatar: true,
              avatarSrc: "https://www.svgrepo.com/show/532363/user-alt-1.svg"
            },
            textInput: {
              placeholder: "Type your query .........",
              backgroundColor: "#ffffff",
              textColor: "#1e1e1f",
              sendButtonColor: "#f36539",
              maxChars: 350,
              maxCharsWarningMessage: "You exceeded the characters limit. Please input less than 350 characters.",
              autoFocus: true,
              borderRadius: 20,
              sendButtonBorderRadius: 50
            },
            uploadsConfig: {
              enabled: false,
              acceptFileTypes: [
                "png",
                "jpeg",
                "jpg",
                "pdf"
              ],
              maxSizeInMB: 5,
              maxFiles: 1
            },
            voiceInputConfig: {
              enabled: false,
              maxRecordingTime: 10,
              recordingNotSupportedMessage: "To record audio, use modern browsers like Chrome or Firefox that support audio recording"
            }
          }
        }
      });
    `;
      document.body.appendChild(script);
    });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initN8nChat);
} else {
  initN8nChat();
}
