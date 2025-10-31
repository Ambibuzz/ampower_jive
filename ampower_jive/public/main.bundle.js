window.__VUE_PROD_HYDRATION_MISMATCH_DETAILS__ = false;

<<<<<<< Updated upstream
function initChat() {
  import('@n8n/chat').then(({ createChat }) => {
    createChat({
      webhookUrl: '{Enter N8N webhook URL}',
      target: '#n8n-chat',
      chatTitle: 'Ampower Jive',
      position: 'bottom-right',
      initialMessages: [
        'My name is Jive. How can I assist you today?'
      ],
      theme: { primary: '#2563eb' },
=======
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
>>>>>>> Stashed changes
    });
  });

  const style = document.createElement("style");
  style.innerHTML = `
  /* Chat window container */
  .chat-window-wrapper.n8n-chat {
    position: fixed !important;
    bottom: 70px !important;
    right: 20px !important;
    max-width: 280px;
    border-radius: 16px;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.15);
    overflow: hidden;
    background: #fff;
    z-index: 9999;
  }

  /* Header */
  .chat-header {
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    color: #fff;
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
  }

  .chat-header h1 {
    font-size: 1rem;
    font-weight: 600;
    margin: 0;
  }

  .chat-header p {
    font-size: 0.8rem;
    margin: 4px 0 0;
    opacity: 0.9;
  }

  /* Chat body scroll */
  .chat-body {
    max-height: 400px;
    overflow-y: auto;
    padding: 10px;
    background: #fafafa;
  }

  /* Bot message bubble */
  .chat-message-from-bot {
    background: #f3f4f6;
    border-radius: 12px;
    padding: 10px 14px;
    margin: 6px 0;
    max-width: 80%;
    font-size: 0.9rem;
  }

  /* User message bubble */
  .chat-message-from-user {
    background: #2563eb;
    color: #fff;
    border-radius: 12px;
    padding: 10px 14px;
    margin: 6px 0;
    max-width: 80%;
    font-size: 0.9rem;
    align-self: flex-end;
  }

  /* Footer input */
  .chat-footer {
    border-top: 1px solid #e5e7eb;
    background: #fff;
    padding: 8px 10px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  /* Input wrapper */
  .chat-inputs {
    display: flex !important;
    align-items: center;
    width: 100% !important;
    gap: 8px !important;
  }

  .chat-inputs textarea {
    flex: 1 !important;
    width: auto !important;
    max-width: calc(100% - 50px) !important;
    border: 1px solid #d1d5db !important;
    border-radius: 20px !important;
    padding: 10px 14px !important;
    font-size: 0.9rem !important;
    outline: none !important;
    resize: none !important;
    min-height: 40px !important;
    background: #fafafa !important;
    box-sizing: border-box !important;
  }

  .chat-inputs-controls {
    flex-shrink: 0 !important;
  }

  /* Send button */
  .chat-input-send-button {
    width: 40px !important;
    height: 40px !important;
    border-radius: 50% !important;
    border: none;
    background: #2563eb !important;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 2px 6px rgba(37, 99, 235, 0.3);
    margin-left: 8px;
  }

  .chat-input-send-button svg {
    width: 18px;
    height: 18px;
    fill: #fff !important;
  }

  .chat-input-send-button:hover {
    background: #1d4ed8;
    transform: scale(1.05);
  }

  /* Toggle button */
  .chat-window-toggle {
    position: fixed !important;
    bottom: 20px !important;
    right: 20px !important;
    width: 40px !important;
    height: 40px !important;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50% !important;
    background: #2563eb !important;
    color: #fff !important;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
    z-index: 9999;
  }

  .chat-window-toggle:hover {
    transform: scale(1.05);
  }
  `;
  document.head.appendChild(style);
}

// Call it when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initChat);
} else {
  initChat();
}
