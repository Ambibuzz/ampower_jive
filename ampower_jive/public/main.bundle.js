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
              enabled: true,
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
              enabled: true,
              maxRecordingTime: 10,
              recordingNotSupportedMessage: "To record audio, use modern browsers like Chrome or Firefox that support audio recording"
            }
          }
        }
      });

      const btn = document.body.querySelector("n8nchatui-popup").shadowRoot.querySelector(".n8n-chat-ui-bot-bubble");

      // Listen for click on chat bubble and update footer after 500ms
      btn && btn.addEventListener('click', () => {
        setTimeout(() => {
          const chatContainer = document.body.querySelector("n8nchatui-popup").shadowRoot.querySelector(".n8n-chat-ui-bot-chat-container");
          const footerSpan = chatContainer.lastChild;

          const newSpan = document.createElement("span");
          newSpan.setAttribute("class", "w-full text-center px-[10px] pt-[6px] pb-[10px] m-auto text-[13px]");
          newSpan.setAttribute("style", "color: rgb(48, 50, 53); background-color: rgb(237, 232, 237);");
          newSpan.innerHTML = 
            'Powered by Open Source | ' +
            '<a target="_blank" rel="noopener noreferrer" class="lite-badge" id="lite-badge" href="https://github.com/Ambibuzz/ampower_jive" style="font-weight: bold; color: rgb(48, 50, 53);">' +
            '<b>AmPower Jive</b>' +
            '</a>';

          footerSpan.replaceWith(newSpan);
        }, 100);
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
