import streamlit as st
import openai
import random
import time
import base64
import re
import json
import numpy as np
from textstat import flesch_reading_ease
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder
from config import OPENAI_API_KEY, INTERVIEW_QUESTIONS

# Configure OpenAI
openai.api_key = OPENAI_API_KEY

# Initialize session state variables
if 'interview_started' not in st.session_state:
    st.session_state.interview_started = False
if 'current_question_index' not in st.session_state:
    st.session_state.current_question_index = 0
if 'category' not in st.session_state:
    st.session_state.category = None
if 'questions' not in st.session_state:
    st.session_state.questions = []
if 'answers' not in st.session_state:
    st.session_state.answers = []
if 'scores' not in st.session_state:
    st.session_state.scores = []
if 'interview_complete' not in st.session_state:
    st.session_state.interview_complete = False
if 'transcribed_text' not in st.session_state:
    st.session_state.transcribed_text = ""

def text_to_speech(text):
    """Convert text to speech using JavaScript Web Speech API"""
    js_code = f"""
    <script>
    if ('speechSynthesis' in window) {{
        const utterance = new SpeechSynthesisUtterance('{text}');
        utterance.rate = 0.9;
        utterance.pitch = 1;
        utterance.volume = 1;
        window.speechSynthesis.speak(utterance);
    }}
    </script>
    """
    st.components.v1.html(js_code, height=0)

def transcribe_audio(audio_data):
    """Convert audio to text using speech recognition"""
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(audio_data) as source:
            audio = recognizer.record(source)
            text = recognizer.recognize_google(audio)
            return text
    except Exception as e:
        st.error(f"Error transcribing audio: {e}")
        return None

def calculate_clarity_score(answer):
    """Improved clarity scoring based on multiple factors"""
    if not answer or len(answer.strip()) < 10:
        return 3.0

    # Calculate readability metrics
    word_count = len(answer.split())
    sentence_count = len(re.split(r'[.!?]', answer)) - 1
    avg_sentence_length = word_count / max(1, sentence_count)

    # Flesch reading ease (higher is better)
    readability = flesch_reading_ease(answer)

    # Calculate clarity score (0-10)
    clarity = 0

    # Base score based on readability
    clarity += min(5, readability / 20)  # Max 5 points from readability

    # Bonus for reasonable sentence length
    if 10 <= avg_sentence_length <= 25:
        clarity += 2
    elif 5 <= avg_sentence_length < 10 or 25 < avg_sentence_length <= 30:
        clarity += 1

    # Bonus for structure (paragraphs, logical flow)
    if '\n' in answer:  # Simple check for paragraph breaks
        clarity += 1

    # Ensure score is between 3-10
    return max(3, min(10, round(clarity, 1)))

def analyze_answer(question, answer, category):
    """Analyze the answer using OpenAI and custom metrics"""
    if not answer or len(answer.strip()) < 10:
        return {
            "overall_score": 1,
            "relevance": 1,
            "completeness": 1,
            "clarity": 3,  # Minimum clarity score
            "accuracy": 1,
            "feedback": "Please provide a more detailed answer."
        }

    # Calculate basic metrics
    word_count = len(answer.split())
    clarity_score = calculate_clarity_score(answer)

    # OpenAI analysis
    prompt = f"""
    Analyze this interview answer for a {category} interview:

    Question: {question}
    Answer: {answer}

    Provide a JSON response with:
    - relevance_score (0-10): How relevant is the answer to the question?
    - completeness_score (0-10): How complete and detailed is the answer?
    - accuracy_score (0-10): How accurate is the content?
    - specific_feedback: Brief feedback on strengths and areas for improvement
    - suggestions: 1-2 specific suggestions for improvement

    Be encouraging but fair. Good answers should score 6-8, excellent answers 8-10.
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert interviewer analyzing responses. Provide JSON output only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        analysis = json.loads(response.choices[0].message.content)

        # Apply scoring adjustments
        relevance = min(10, max(3, analysis.get("relevance_score", 5)))
        completeness = min(10, max(3, analysis.get("completeness_score", 5) + (1 if word_count > 50 else 0)))
        accuracy = min(10, max(3, analysis.get("accuracy_score", 5)))

        # Calculate overall score with weighted components
        overall_score = (relevance * 0.3 + completeness * 0.3 + clarity_score * 0.2 + accuracy * 0.2)

        return {
            "overall_score": round(overall_score, 1),
            "relevance": round(relevance, 1),
            "completeness": round(completeness, 1),
            "clarity": clarity_score,
            "accuracy": round(accuracy, 1),
            "feedback": analysis.get("specific_feedback", "Good effort! Try to be more specific."),
            "suggestions": analysis.get("suggestions", ["Provide more specific examples", "Structure your answer more clearly"])
        }
    except Exception as e:
        # Fallback scoring
        return {
            "overall_score": min(7, max(3, word_count / 10)),
            "relevance": min(7, max(3, word_count / 10)),
            "completeness": min(7, max(3, word_count / 15)),
            "clarity": clarity_score,
            "accuracy": min(7, max(3, word_count / 12)),
            "feedback": "Good effort! Try to provide more specific examples.",
            "suggestions": ["Practice structuring your answers", "Use the STAR method for behavioral questions"]
        }

def calculate_final_scores():
    """Calculate final interview scores"""
    if not st.session_state.scores:
        return None

    avg_scores = {
        "overall": np.mean([s["overall_score"] for s in st.session_state.scores]),
        "relevance": np.mean([s["relevance"] for s in st.session_state.scores]),
        "completeness": np.mean([s["completeness"] for s in st.session_state.scores]),
        "clarity": np.mean([s["clarity"] for s in st.session_state.scores]),
        "accuracy": np.mean([s["accuracy"] for s in st.session_state.scores])
    }

    # Generate aggregated feedback
    strengths = []
    improvements = []
    all_suggestions = []

    for score in st.session_state.scores:
        all_suggestions.extend(score.get("suggestions", []))

    for category, score in avg_scores.items():
        if category != "overall" and score >= 7:
            strengths.append(f"Strong {category}")
        elif category != "overall" and score < 5:
            improvements.append(f"Improve {category}")

    # Get unique suggestions
    unique_suggestions = list(set(all_suggestions))

    return {
        "scores": avg_scores,
        "strengths": strengths if strengths else ["Good overall performance"],
        "improvements": improvements if improvements else ["Continue practicing to enhance your skills"],
        "suggestions": unique_suggestions[:3],  # Top 3 suggestions
        "grade": get_grade(avg_scores["overall"])
    }

def get_grade(score):
    """Convert score to letter grade"""
    if score >= 9:
        return "A+ (Excellent)"
    elif score >= 8:
        return "A (Very Good)"
    elif score >= 7:
        return "B+ (Good)"
    elif score >= 6:
        return "B (Satisfactory)"
    elif score >= 5:
        return "C (Needs Improvement)"
    else:
        return "D (Requires Significant Improvement)"

def main():
    # Custom CSS for colorful theme
    st.markdown("""
    <style>
    .main {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }
    .stApp {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    }
    .question-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
        margin: 10px 0;
    }
    .answer-box {
        background: white;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin: 10px 0;
    }
    .score-box {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        padding: 15px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .progress-bar {
        background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%);
        height: 10px;
        border-radius: 5px;
    }
    .category-card {
        background: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin: 10px;
        transition: transform 0.3s;
    }
    .category-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 6px 12px rgba(0,0,0,0.15);
    }
    .metric-card {
        background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
        padding: 10px;
        border-radius: 8px;
        color: white;
        text-align: center;
    }
    .suggestion-box {
        background: #008000;
        padding: 15px;
        border-radius: 8px;
        border-left: 4px solid #2e7d32;
        margin: 10px 0;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("🎤 AI Interview Practice Agent")
    st.markdown("---")

    if not st.session_state.interview_started:
        # Welcome screen
        st.markdown("### 🚀 Welcome to Your Personal AI Interview Coach!")
        st.markdown("Practice your interview skills with AI-powered feedback across multiple categories.")

        st.markdown("### Select Interview Category:")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("💻 Technical Interview", key="tech", help="Practice technical questions"):
                st.session_state.category = "Technical"
                st.session_state.questions = random.sample(INTERVIEW_QUESTIONS["Technical"], 8)
                st.session_state.interview_started = True
                st.rerun()

            if st.button("🤝 Behavioral Interview", key="behav", help="Practice behavioral questions"):
                st.session_state.category = "Behavioral"
                st.session_state.questions = random.sample(INTERVIEW_QUESTIONS["Behavioral"], 8)
                st.session_state.interview_started = True
                st.rerun()

        with col2:
            if st.button("👔 Management Interview", key="mgmt", help="Practice management questions"):
                st.session_state.category = "Management"
                st.session_state.questions = random.sample(INTERVIEW_QUESTIONS["Management"], 8)
                st.session_state.interview_started = True
                st.rerun()

            if st.button("📈 Sales & Marketing Interview", key="sales", help="Practice sales questions"):
                st.session_state.category = "Sales & Marketing"
                st.session_state.questions = random.sample(INTERVIEW_QUESTIONS["Sales & Marketing"], 8)
                st.session_state.interview_started = True
                st.rerun()

        # Instructions
        st.markdown("---")
        st.markdown("### 📋 How It Works:")
        st.markdown("""
        1. **Choose a category** from the options above
        2. **Answer 8 questions** either by typing or speaking
        3. **Get instant AI feedback** on each response
        4. **Receive a comprehensive score** and improvement suggestions
        5. **Practice regularly** to improve your interview skills!
        """)

    elif st.session_state.interview_complete:
        # Results screen
        final_results = calculate_final_scores()

        st.markdown("### 🎉 Interview Complete!")
        st.markdown("---")

        # Overall Score
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown(f"""
            <div class="score-box">
                <h2>Overall Score: {final_results['scores']['overall']:.1f}/10</h2>
                <h3>{final_results['grade']}</h3>
            </div>
            """, unsafe_allow_html=True)

        # Detailed Scores
        st.markdown("### 📊 Detailed Breakdown:")
        col1, col2, col3, col4 = st.columns(4)

        metrics = [
            ("Relevance", final_results['scores']['relevance']),
            ("Completeness", final_results['scores']['completeness']),
            ("Clarity", final_results['scores']['clarity']),
            ("Accuracy", final_results['scores']['accuracy'])
        ]

        for i, (metric, score) in enumerate(metrics):
            with [col1, col2, col3, col4][i]:
                st.markdown(f"""
                <div class="metric-card">
                    <h4>{metric}</h4>
                    <h3>{score:.1f}/10</h3>
                </div>
                """, unsafe_allow_html=True)

        # Strengths and Improvements
        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### ✅ Strengths:")
            for strength in final_results['strengths']:
                st.markdown(f"• {strength}")

        with col2:
            st.markdown("### 🎯 Areas for Improvement:")
            for improvement in final_results['improvements']:
                st.markdown(f"• {improvement}")

        # Suggestions
        st.markdown("---")
        st.markdown("### 💡 Top Suggestions for Improvement:")
        for suggestion in final_results['suggestions']:
            st.markdown(f"""
            <div class="suggestion-box">
                {suggestion}
            </div>
            """, unsafe_allow_html=True)

        # Question-wise feedback
        st.markdown("---")
        st.markdown("### 📝 Question-wise Feedback:")

        for i, (question, answer, score) in enumerate(zip(st.session_state.questions,
                                                          st.session_state.answers,
                                                          st.session_state.scores)):
            with st.expander(f"Question {i+1} - Score: {score['overall_score']}/10"):
                st.markdown(f"**Q:** {question}")
                st.markdown(f"**A:** {answer}")
                st.markdown(f"**Feedback:** {score['feedback']}")
                if 'suggestions' in score:
                    st.markdown("**Suggestions:**")
                    for sugg in score['suggestions']:
                        st.markdown(f"- {sugg}")

        # Restart button
        if st.button("🔄 Start New Interview", key="restart"):
            for key in st.session_state.keys():
                del st.session_state[key]
            st.rerun()

    else:
        # Interview in progress
        current_q = st.session_state.current_question_index

        # Progress bar
        progress = (current_q + 1) / 8
        st.progress(progress)
        st.markdown(f"### Question {current_q + 1} of 8")

        # Display question
        question = st.session_state.questions[current_q]
        st.markdown(f"""
        <div class="question-box">
            <h3>📌 {question}</h3>
        </div>
        """, unsafe_allow_html=True)

        # Text to speech button
        if st.button("🔊 Hear Question", key="speak_q"):
            text_to_speech(question)

        # Answer input
        st.markdown("### Your Answer:")

        # Text input (pre-filled with transcription if available)
        answer = st.text_area(
            "Type your answer here:",
            value=st.session_state.transcribed_text,
            height=150,
            key=f"answer_{current_q}",
            placeholder="Share your detailed response here..."
        )

        # Submit button
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("✅ Submit Answer", key="submit", type="primary", use_container_width=True):
                if answer and len(answer.strip()) > 10:
                    # Analyze answer
                    analysis = analyze_answer(question, answer, st.session_state.category)

                    # Store results
                    st.session_state.answers.append(answer)
                    st.session_state.scores.append(analysis)

                    # Show feedback
                    st.markdown("---")
                    st.markdown("### 📊 Your Score:")
                    col1, col2, col3, col4, col5 = st.columns(5)

                    with col1:
                        st.metric("Overall", f"{analysis['overall_score']}/10")
                    with col2:
                        st.metric("Relevance", f"{analysis['relevance']}/10")
                    with col3:
                        st.metric("Completeness", f"{analysis['completeness']}/10")
                    with col4:
                        st.metric("Clarity", f"{analysis['clarity']}/10")
                    with col5:
                        st.metric("Accuracy", f"{analysis['accuracy']}/10")

                    st.markdown(f"**💡 Feedback:** {analysis['feedback']}")
                    if 'suggestions' in analysis:
                        st.markdown("**Suggestions:**")
                        for sugg in analysis['suggestions']:
                            st.markdown(f"- {sugg}")

                    # Move to next question or complete
                    if current_q < 7:
                        st.session_state.current_question_index += 1
                        st.session_state.transcribed_text = ""  # Reset transcription
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.session_state.interview_complete = True
                        st.rerun()
                else:
                    st.error("⚠️ Please provide a more detailed answer (at least 10 words).")

        # Skip question option
        if st.button("⏭️ Skip Question", key="skip"):
            st.session_state.answers.append("[Skipped]")
            st.session_state.scores.append({
                "overall_score": 0,
                "relevance": 0,
                "completeness": 0,
                "clarity": 3,
                "accuracy": 0,
                "feedback": "Question was skipped.",
                "suggestions": ["Try to answer all questions", "Practice time management"]
            })

            if current_q < 7:
                st.session_state.current_question_index += 1
                st.session_state.transcribed_text = ""  # Reset transcription
                st.rerun()
            else:
                st.session_state.interview_complete = True
                st.rerun()

if __name__ == "__main__":
    main()