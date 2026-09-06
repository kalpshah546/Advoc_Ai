import html
import logging
import re
import textwrap
from typing import Any, Dict, List, Tuple

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.conf import settings
from .models import DocumentSession, ChatMessage
from authentication.models import User
import fitz  # PyMuPDF for PDF
from docx import Document
from mongoengine import DoesNotExist
from utils.gemini_client import get_gemini_client, _get_llm_model_name # Import from centralized utility


logger = logging.getLogger(__name__)


# Import generalized false positive prevention framework
try:
    from .false_positive_prevention import (
        should_filter_clause,
        validate_category_consistency,
        detect_identical_replacement,
        get_balancing_examples_for_prompt
    )
    FP_FRAMEWORK_AVAILABLE = True
except ImportError:
    FP_FRAMEWORK_AVAILABLE = False

# Import two-stage solution refinement
try:
    from .solution_refinement import (
        refine_clause_solutions_with_patterns_and_llm,
        batch_refine_clauses
    )
    SOLUTION_REFINEMENT_AVAILABLE = True
except ImportError:
    SOLUTION_REFINEMENT_AVAILABLE = False
    logger.warning("Solution refinement module not available")




def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace for better matching"""
    return re.sub(r'\s+', ' ', text).strip()


def _strip_section_header(text: str) -> str:
    """
    Remove common section headers/numbering from clause text.
    Examples: "10.1", "Section 5", "Article III", etc.
    """
    import re
    # Remove leading section numbers like "10.1", "5.2.3", etc.
    text = re.sub(r'^\s*\d+(\.\d+)*\s*', '', text)
    # Remove "Section X", "Article Y", etc.
    text = re.sub(r'^\s*(Section|Article|Clause|Paragraph)\s+[IVXLCDM\d]+[\.\:)]*\s*', '', text, flags=re.IGNORECASE)
    # Remove standalone headers at start
    text = re.sub(r'^[A-Z][a-z]+\s+\d+(\.\d+)*\s+', '', text)
    return text.strip()


def _find_best_match(full_text: str, snippet: str, min_match_length: int = 30) -> Tuple[int, int]:
    """
    Find the best match for a snippet in the full text using multiple strategies.
    
    Returns: (start_index, end_index) or (-1, -1) if not found
    """
    if not snippet or not full_text:
        return (-1, -1)
    
    snippet = snippet.strip()
    
    # Strategy 1: Exact match
    start_index = full_text.find(snippet)
    if start_index != -1:
        return (start_index, start_index + len(snippet))
    
    # Strategy 2: Case-insensitive exact match
    lower_text = full_text.lower()
    lower_snippet = snippet.lower()
    start_index = lower_text.find(lower_snippet)
    if start_index != -1:
        return (start_index, start_index + len(snippet))
    
    # Strategy 3: Strip section headers and try again
    stripped_snippet = _strip_section_header(snippet)
    if stripped_snippet and len(stripped_snippet) >= min_match_length:
        # Try exact match without section header
        start_index = full_text.find(stripped_snippet)
        if start_index != -1:
            # Find the actual start (may include header in document)
            search_start = max(0, start_index - 50)
            return (search_start, start_index + len(stripped_snippet))
        
        # Try case-insensitive without section header
        start_index = lower_text.find(stripped_snippet.lower())
        if start_index != -1:
            search_start = max(0, start_index - 50)
            return (search_start, start_index + len(stripped_snippet))
    
    # Strategy 4: Normalized whitespace match
    normalized_snippet = _normalize_whitespace(snippet)
    if len(normalized_snippet) < min_match_length:
        return (-1, -1)
    
    # Create normalized version for comparison
    normalized_full = _normalize_whitespace(full_text)
    norm_start = normalized_full.lower().find(normalized_snippet.lower())
    
    if norm_start != -1:
        # Map back to original text position (approximate)
        # Count non-whitespace chars to find position
        char_count = 0
        start_index = 0
        for i, char in enumerate(full_text):
            if not char.isspace():
                char_count += 1
            if char_count >= norm_start:
                start_index = i
                break
        
        # Find end by matching characters
        snippet_chars = [c for c in normalized_snippet.lower() if not c.isspace()]
        matched_chars = 0
        end_index = start_index
        
        for i in range(start_index, len(full_text)):
            if matched_chars >= len(snippet_chars):
                end_index = i
                break
            if not full_text[i].isspace():
                if full_text[i].lower() == snippet_chars[matched_chars]:
                    matched_chars += 1
                else:
                    # Mismatch, try from next position
                    break
        
        if matched_chars >= len(snippet_chars) * 0.9:  # 90% match
            return (start_index, end_index)
    
    # Strategy 5: Try with stripped snippet and normalized whitespace
    if stripped_snippet and len(stripped_snippet) >= min_match_length:
        normalized_stripped = _normalize_whitespace(stripped_snippet)
        norm_start = normalized_full.lower().find(normalized_stripped.lower())
        
        if norm_start != -1:
            char_count = 0
            start_index = 0
            for i, char in enumerate(full_text):
                if not char.isspace():
                    char_count += 1
                if char_count >= norm_start:
                    start_index = max(0, i - 50)  # Include potential header
                    break
            
            snippet_chars = [c for c in normalized_stripped.lower() if not c.isspace()]
            matched_chars = 0
            
            for i in range(start_index, len(full_text)):
                if matched_chars >= len(snippet_chars):
                    end_index = i
                    break
                if not full_text[i].isspace():
                    if full_text[i].lower() == snippet_chars[matched_chars]:
                        matched_chars += 1
            
            if matched_chars >= len(snippet_chars) * 0.85:  # 85% match for stripped
                return (start_index, end_index)
    
    # Strategy 6: Find core phrase (first substantial words, skip section headers)
    snippet_for_words = _strip_section_header(snippet)
    words = [w for w in snippet_for_words.split() if len(w) > 3][:10]  # First 10 significant words
    
    if len(words) >= 3:
        # Try progressively smaller core phrases
        for phrase_length in [7, 5, 4, 3]:
            if len(words) >= phrase_length:
                core_phrase = ' '.join(words[:phrase_length])
                start_index = lower_text.find(core_phrase.lower())
                if start_index != -1:
                    # Extend to reasonable clause boundary
                    end_index = start_index + min(len(snippet), 500)
                    # Try to end at sentence boundary
                    for i in range(end_index, min(end_index + 150, len(full_text))):
                        if full_text[i] in '.!?\n':
                            end_index = i + 1
                            break
                    return (max(0, start_index - 30), end_index)
    
    return (-1, -1)


def _expand_to_sentence_boundary(text: str, start: int, end: int) -> Tuple[int, int]:
    """Expand the range to complete sentence boundaries.
    
    Expands backwards to find the start of the sentence and forwards to find the end.
    This ensures highlighted clauses are complete and coherent.
    """
    # Find sentence start (capital letter after period, or start of text)
    sentence_start = start
    for i in range(start - 1, max(0, start - 200), -1):
        if text[i] in '.!?\n':
            # Found potential sentence end, next sentence starts after whitespace
            sentence_start = i + 1
            while sentence_start < start and text[sentence_start].isspace():
                sentence_start += 1
            break
        # Check for numbered sections like "1.1" or "(a)"
        if i > 0 and text[i].isdigit() and text[i-1] == '\n':
            sentence_start = i
            break
    
    # Find sentence end (period, exclamation, question mark)
    sentence_end = end
    for i in range(end, min(len(text), end + 300)):
        if text[i] in '.!?':
            # Include the punctuation and any trailing space
            sentence_end = i + 1
            while sentence_end < len(text) and text[sentence_end] in ' \t':
                sentence_end += 1
            break
        # Stop at double newline (paragraph break)
        if i < len(text) - 1 and text[i:i+2] == '\n\n':
            sentence_end = i
            break
    
    return (sentence_start, sentence_end)


def _build_highlighted_preview(full_text: str, clauses: List[Dict[str, Any]]) -> Tuple[str, List[int], Dict[int, str]]:
    """Return HTML-safe preview text with risky clauses wrapped in <mark> tags.
    
    Returns:
        Tuple of (highlighted_html, successfully_highlighted_indices, expanded_clause_texts)
        where expanded_clause_texts maps clause_idx -> expanded full sentence text
    """
    if not full_text:
        return "", [], {}

    if not clauses:
        return html.escape(full_text).replace('\n', '<br />'), [], {}

    matches: List[Tuple[int, int, int, int]] = []  # (start, end, risk_score, clause_index)
    successfully_highlighted: List[int] = []  # Track which clause indices were highlighted
    expanded_clause_texts: Dict[int, str] = {}  # Map clause_idx -> expanded sentence text
    lower_text = full_text.lower()

    for clause_idx, clause in enumerate(clauses):
        snippet = (
            clause.get('clause_text')
            or clause.get('clause')
            or clause.get('text')
            or ""
        ).strip()
        if not snippet:
            continue

        risk_score = clause.get('risk_score', 3)
        start_index, end_index = _find_best_match(full_text, snippet)
        
        if start_index == -1:
            # Log with more context for debugging
            stripped = _strip_section_header(snippet)
            logger.warning(
                f"Could not highlight clause (original: '{snippet[:60]}...', "
                f"stripped: '{stripped[:60]}...'). "
                f"Trying partial match as last resort."
            )
            
            # Last resort: find ANY significant portion (at least 50 chars)
            if len(snippet) > 50:
                # Try last 100 chars (often the actual clause content)
                tail = snippet[-100:].strip()
                if len(tail) > 40:
                    start_index = lower_text.find(tail.lower())
                    if start_index != -1:
                        end_index = start_index + len(tail)
                        logger.info(f"Found using tail match: '{tail[:40]}...'")
                    else:
                        # Try middle 100 chars
                        mid_start = len(snippet) // 4
                        middle = snippet[mid_start:mid_start+100].strip()
                        if len(middle) > 40:
                            start_index = lower_text.find(middle.lower())
                            if start_index != -1:
                                end_index = start_index + len(middle)
                                logger.info(f"Found using middle match: '{middle[:40]}...'")
        
        if start_index == -1:
            logger.warning(f"Skipping highlight for clause: {snippet[:80]}...")
            continue
        
        # Expand to complete sentence boundaries for coherent highlighting
        start_index, end_index = _expand_to_sentence_boundary(full_text, start_index, end_index)
        expanded_text = full_text[start_index:end_index].strip()
        expanded_clause_texts[clause_idx] = expanded_text
        logger.info(f"Expanded clause to sentence boundaries: [{start_index}:{end_index}] = '{expanded_text[:60]}...'")

        # Check for overlaps - only merge if they're truly the same clause (>70% overlap)
        # Allow adjacent or slightly overlapping different clauses to coexist
        has_significant_overlap = False
        for i, (existing_start, existing_end, existing_risk, existing_idx) in enumerate(matches):
            overlap_start = max(start_index, existing_start)
            overlap_end = min(end_index, existing_end)
            overlap_length = max(0, overlap_end - overlap_start)
            
            # Calculate overlap percentage relative to both clauses
            current_length = end_index - start_index
            existing_length = existing_end - existing_start
            
            # Check overlap from both perspectives
            overlap_of_current = overlap_length / current_length if current_length > 0 else 0
            overlap_of_existing = overlap_length / existing_length if existing_length > 0 else 0
            
            # Only treat as duplicate if BOTH clauses have >70% overlap
            # This means they're essentially the same clause, not just adjacent
            if overlap_of_current > 0.7 and overlap_of_existing > 0.7:
                # This is a duplicate detection of the same clause - keep higher risk
                if risk_score > existing_risk:
                    # Replace existing with current
                    matches[i] = (start_index, end_index, risk_score, clause_idx)
                    # Update successfully_highlighted and expanded texts
                    if existing_idx in successfully_highlighted:
                        successfully_highlighted.remove(existing_idx)
                    if existing_idx in expanded_clause_texts:
                        del expanded_clause_texts[existing_idx]
                    successfully_highlighted.append(clause_idx)
                    logger.info(f"Duplicate clause detected (overlap {overlap_of_current:.0%}/{overlap_of_existing:.0%}): replacing with higher risk")
                else:
                    # Keep existing, skip current - remove current's expanded text
                    if clause_idx in expanded_clause_texts:
                        del expanded_clause_texts[clause_idx]
                    logger.info(f"Duplicate clause detected (overlap {overlap_of_current:.0%}/{overlap_of_existing:.0%}): keeping existing higher risk")
                has_significant_overlap = True
                break
            elif overlap_length > 0:
                # Some overlap but not duplicates - these are different adjacent clauses
                # Log but allow both to exist
                logger.info(f"Adjacent clauses with minor overlap ({overlap_length} chars): keeping both separate")
        
        if not has_significant_overlap:
            matches.append((start_index, end_index, risk_score, clause_idx))
            successfully_highlighted.append(clause_idx)

    # Sort matches by position
    matches.sort(key=lambda x: x[0])

    if not matches:
        logger.warning(f"No clauses could be highlighted from {len(clauses)} detected risks")
        return html.escape(full_text).replace('\n', '<br />'), []

    highlighted_parts: List[str] = []
    previous_end = 0

    for start_index, end_index, risk_score, clause_idx in matches:
        # Add text before the match
        highlighted_parts.append(html.escape(full_text[previous_end:start_index]))
        
        # Add highlighted match with risk level class
        snippet = full_text[start_index:end_index]
        risk_level = 'high' if risk_score >= 4 else 'medium' if risk_score >= 3 else 'low'
        highlighted_parts.append(
            f"<mark class=\"risk-{risk_level}\" data-risk-score=\"{risk_score}\">{html.escape(snippet)}</mark>"
        )
        previous_end = end_index

    highlighted_parts.append(html.escape(full_text[previous_end:]))
    highlighted_html = ''.join(highlighted_parts)
    
    logger.info(f"Successfully highlighted {len(successfully_highlighted)} out of {len(clauses)} clauses")
    return highlighted_html.replace('\n', '<br />'), list(set(successfully_highlighted)), expanded_clause_texts


def _generate_mock_analysis(full_text: str, preview_excerpt: str, truncated_document: str) -> Dict[str, Any]:
    """Fallback analysis when Gemini is not configured or LangChain fails."""
    logger.warning("Using mock analysis for document summarization.")

    fallback_summary = textwrap.shorten(
        truncated_document.replace('\n', ' '),
        width=500,
        placeholder='…'
    ) if truncated_document else ""

    safe_full_text = full_text or preview_excerpt or ''
    highlighted_preview = html.escape(safe_full_text).replace('\n', '<br />') if safe_full_text else ""
    highlighted_indices = []
    expanded_texts = {}

    return {
        'summary': fallback_summary or 'AI summarization is unavailable without a configured Gemini API key.',
        'high_risk_clauses': [],
        'highlighted_preview': highlighted_preview,
        'preview_text': safe_full_text,
        'source': 'fallback'
    }


RISK_KEYWORDS: List[Dict[str, Any]] = [
    {'pattern': 'shall indemnify', 'rationale': 'Broad indemnity can transfer extensive liability to you.', 'weight': 5, 'default_score': 5, 'suggestion': 'Limit indemnity to third-party losses caused by the indemnifying party and cap recoverable damages.', 'replacement_category': 'indemnity'},
    {'pattern': 'indemnify', 'rationale': 'Indemnification language often shifts responsibility for losses.', 'weight': 4, 'default_score': 5, 'suggestion': 'Seek mutual indemnities and restrict scope to negligence or breach documented by the indemnifying party.', 'replacement_category': 'indemnity'},
    {'pattern': 'indemnity', 'rationale': 'Indemnity terms may create unlimited loss exposure.', 'weight': 4, 'default_score': 5, 'suggestion': 'Tie indemnity to specific, provable harms and add financial caps or insurance requirements.', 'replacement_category': 'indemnity'},
    {'pattern': 'hold harmless', 'rationale': 'Hold harmless obligations can expand your liability exposure.', 'weight': 4, 'default_score': 5, 'suggestion': 'Convert hold harmless language to mutual indemnities or limit to direct damages from proven misconduct.', 'replacement_category': 'indemnity'},
    {'pattern': 'defend and indemnify', 'rationale': 'Defense obligations add cost and litigation risk.', 'weight': 4, 'default_score': 5, 'suggestion': 'Remove the duty to defend or make reimbursement contingent on proven liability and reasonable costs.', 'replacement_category': 'indemnity'},
    {'pattern': 'limitation of liability', 'rationale': 'Liability caps may be one-sided or exclude key damages.', 'weight': 4, 'default_score': 4, 'suggestion': 'Ensure liability caps are mutual, tied to fees, and carve out critical losses like data breaches or IP infringement.', 'replacement_category': 'liability_cap'},
    {'pattern': 'limitation on liability', 'rationale': 'Liability caps may be one-sided or exclude key damages.', 'weight': 4, 'default_score': 4, 'suggestion': 'Increase the liability cap to a realistic amount and add carve-outs for gross negligence or willful misconduct.', 'replacement_category': 'liability_cap'},
    {'pattern': 'liability shall not exceed', 'rationale': 'Dollar caps on liability can be too low for the risk.', 'weight': 4, 'default_score': 4, 'suggestion': 'Link the liability cap to total contract value or annual fees and carve out critical categories of harm.', 'replacement_category': 'liability_cap'},
    {'pattern': 'limitation on remedies', 'rationale': 'Limits on remedies may prevent adequate recourse.', 'weight': 3, 'default_score': 4, 'suggestion': 'Add supplemental remedies or exceptions when the primary remedy fails to deliver the contracted outcome.', 'replacement_category': 'remedies'},
    {'pattern': 'exclusive remedy', 'rationale': 'Exclusive remedy clauses restrict available recourse.', 'weight': 3, 'default_score': 4, 'suggestion': 'Allow alternative remedies if the exclusive remedy fails or if breaches are material or repeated.', 'replacement_category': 'remedies'},
    {'pattern': 'waiver of consequential', 'rationale': 'Waives indirect damages that may be necessary to recover.', 'weight': 3, 'default_score': 4, 'suggestion': "Carve out consequential damages arising from the other party's breach, data loss, or IP infringement.", 'replacement_category': 'remedies'},
    {'pattern': 'warranty disclaimer', 'rationale': 'Warranty disclaimers can remove important protections.', 'weight': 3, 'default_score': 4, 'suggestion': 'Add baseline performance warranties or acceptance testing to ensure minimum service standards.', 'replacement_category': 'warranty'},
    {'pattern': 'provided on an as-is basis', 'rationale': 'As-is language may waive key warranties.', 'weight': 3, 'default_score': 3, 'suggestion': 'Insert performance commitments or a right to terminate if the deliverable fails agreed specifications.', 'replacement_category': 'warranty'},
    {'pattern': 'liquidated damages', 'rationale': 'Preset damages may be punitive or costly.', 'weight': 4, 'default_score': 4, 'suggestion': 'Verify liquidated damages align with actual anticipated loss and cap total exposure.', 'replacement_category': 'penalties'},
    {'pattern': 'early termination fee', 'rationale': 'Termination penalties can be financially burdensome.', 'weight': 3, 'default_score': 4, 'suggestion': 'Negotiate prorated termination fees tied to unrecovered costs or limit the fee to a short notice period.', 'replacement_category': 'penalties'},
    {'pattern': 'penalty', 'rationale': 'Penalty provisions may create significant financial exposure.', 'weight': 3, 'default_score': 4, 'suggestion': 'Replace punitive penalties with reasonable liquidated damages or cure rights before charges apply.', 'replacement_category': 'penalties'},
    {'pattern': 'termination for convenience', 'rationale': 'Termination for convenience without notice harms contract stability.', 'weight': 4, 'default_score': 4, 'suggestion': 'Add reasonable notice periods, mutual termination rights, and reimbursement of non-recoverable costs.', 'replacement_category': 'termination'},
    {'pattern': 'terminate at any time', 'rationale': 'Unqualified termination rights create uncertainty.', 'weight': 3, 'default_score': 4, 'suggestion': 'Require advance notice, minimum commitment, or limit termination to defined trigger events.', 'replacement_category': 'termination'},
    {'pattern': 'automatic renewal', 'rationale': 'Automatic renewal clauses can extend obligations without explicit consent.', 'weight': 4, 'default_score': 4, 'suggestion': 'Shorten the renewal term, add renewal reminders, and allow opt-out with reasonable notice.', 'replacement_category': 'renewal'},
    {'pattern': 'auto-renew', 'rationale': 'Automatic renewal clauses can extend obligations without explicit consent.', 'weight': 3, 'default_score': 4, 'suggestion': 'Require written confirmation for renewal and reduce advance notice requirements.', 'replacement_category': 'renewal'},
    {'pattern': 'perpetual term', 'rationale': 'Perpetual terms lock parties into long commitments.', 'weight': 3, 'default_score': 4, 'suggestion': 'Add periodic renewal checkpoints or a right to terminate without penalty after an initial term.', 'replacement_category': 'renewal'},
    {'pattern': 'arbitration', 'rationale': 'Mandatory arbitration impacts dispute resolution rights.', 'weight': 3, 'default_score': 3, 'suggestion': 'Ensure arbitration rules, venue, and costs are balanced and preserve access to courts for injunctive relief.', 'replacement_category': 'dispute_resolution'},
    {'pattern': 'binding arbitration', 'rationale': 'Mandatory arbitration impacts dispute resolution rights.', 'weight': 3, 'default_score': 3, 'suggestion': 'Make arbitration mutual, choose a neutral forum, and allow appeals for manifest error or injunctive relief in court.', 'replacement_category': 'dispute_resolution'},
    {'pattern': 'waiver of jury trial', 'rationale': 'Waiving jury trial limits litigation options.', 'weight': 3, 'default_score': 3, 'suggestion': 'Consider removing the waiver or ensure it is mutual and limited to defined dispute types.', 'replacement_category': 'dispute_resolution'},
    {'pattern': 'governing law', 'rationale': 'Governing law in an unfavorable venue can affect outcomes.', 'weight': 2, 'default_score': 3, 'suggestion': 'Renegotiate governing law to a neutral or home jurisdiction that aligns with your legal protections.', 'replacement_category': 'jurisdiction'},
    {'pattern': 'exclusive jurisdiction', 'rationale': 'Exclusive jurisdiction may create unfavorable litigation venues.', 'weight': 2, 'default_score': 3, 'suggestion': 'Allow litigation in your local courts or agree to a mutually convenient jurisdiction.', 'replacement_category': 'jurisdiction'},
    {'pattern': 'venue shall be', 'rationale': 'Fixed venue may require litigating in distant courts.', 'weight': 2, 'default_score': 3, 'suggestion': 'Amend venue provision to include your jurisdiction or permit remote dispute resolution.', 'replacement_category': 'jurisdiction'},
    {'pattern': 'limitation period', 'rationale': 'Reduced limitation periods can curtail legal remedies.', 'weight': 2, 'default_score': 3, 'suggestion': 'Extend limitation periods to statutory defaults or a timeframe that reflects the transaction risk.', 'replacement_category': 'jurisdiction'},
    {'pattern': 'confidentiality', 'rationale': 'Strict confidentiality clauses may impose burdensome restrictions.', 'weight': 2, 'default_score': 3, 'suggestion': 'Ensure confidentiality is mutual, includes standard carve-outs, and limits survival to a reasonable duration.', 'replacement_category': 'confidentiality'},
    {'pattern': 'non-disclosure', 'rationale': 'Strict confidentiality clauses may impose burdensome restrictions.', 'weight': 2, 'default_score': 3, 'suggestion': 'Add carve-outs for legal disclosures, advisors, and information already known or independently developed.', 'replacement_category': 'confidentiality'},
    {'pattern': 'unilateral amendment', 'rationale': 'Unilateral amendment rights allow one party to change terms without consent.', 'weight': 4, 'default_score': 4, 'suggestion': 'Require mutual agreement or give the non-amending party termination rights if changes are unacceptable.', 'replacement_category': 'amendment'},
    {'pattern': 'may modify this agreement', 'rationale': 'Allowing unilateral changes adds significant uncertainty.', 'weight': 3, 'default_score': 4, 'suggestion': 'Add prior notice requirements and allow rejection of material changes without penalty.', 'replacement_category': 'amendment'},
    {'pattern': 'sole discretion', 'rationale': 'Sole discretion terms often grant broad unilateral power.', 'weight': 3, 'default_score': 3, 'suggestion': 'Qualify discretion so it may not be unreasonably withheld, conditioned, or delayed.', 'replacement_category': 'discretion'},
    {'pattern': 'sole and absolute discretion', 'rationale': 'Absolute discretion eliminates checks and balances.', 'weight': 4, 'default_score': 4, 'suggestion': 'Replace with objective criteria or require written consent that cannot be unreasonably withheld.', 'replacement_category': 'discretion'},
    {'pattern': 'assignment without consent', 'rationale': 'Assignments without consent can shift obligations to unknown parties.', 'weight': 3, 'default_score': 3, 'suggestion': 'Limit assignment to affiliates meeting financial criteria or require prior written consent.', 'replacement_category': 'assignment'},
    {'pattern': 'non-compete', 'rationale': 'Non-compete clauses restrict future business opportunities.', 'weight': 3, 'default_score': 3, 'suggestion': 'Narrow the non-compete scope, geography, and term or remove it entirely if unnecessary.', 'replacement_category': 'competition'},
    {'pattern': 'non-solicitation', 'rationale': 'Non-solicitation clauses can hinder hiring or client outreach.', 'weight': 2, 'default_score': 2, 'suggestion': 'Limit non-solicitation to direct poaching of employees or clients for a short duration.', 'replacement_category': 'competition'},
    {'pattern': 'intellectual property shall belong', 'rationale': 'Transfers of IP ownership may be unfavorable.', 'weight': 3, 'default_score': 4, 'suggestion': 'Pursue joint ownership or retain ownership with a license grant tailored to the project.', 'replacement_category': 'ip'},
    {'pattern': 'assign all intellectual property', 'rationale': 'Broad IP assignments can forfeit key rights.', 'weight': 3, 'default_score': 4, 'suggestion': 'Restrict assignments to developed deliverables and secure a perpetual license-back.', 'replacement_category': 'ip'},
    {'pattern': 'license is revocable', 'rationale': 'Revocable licenses may undercut usage rights.', 'weight': 2, 'default_score': 3, 'suggestion': 'Negotiate for an irrevocable, perpetual license that survives termination if fees are paid.', 'replacement_category': 'ip'},
    {'pattern': 'data breach', 'rationale': 'Data breach responsibilities may impose heavy obligations.', 'weight': 3, 'default_score': 4, 'suggestion': 'Define security standards, notification timelines, and cost sharing for breach response.', 'replacement_category': 'data_security'},
    {'pattern': 'personally identifiable information', 'rationale': 'PII handling clauses may create compliance burdens.', 'weight': 3, 'default_score': 3, 'suggestion': 'Clarify data protection requirements and ensure the other party maintains compliant safeguards.', 'replacement_category': 'data_security'},
    {'pattern': 'security incident', 'rationale': 'Security incident obligations can be costly or strict.', 'weight': 3, 'default_score': 3, 'suggestion': 'Set reasonable response windows, cooperation obligations, and limits on indemnified costs.', 'replacement_category': 'data_security'},
    {'pattern': 'service level credit', 'rationale': 'SLA credits can accumulate and erode revenue.', 'weight': 2, 'default_score': 3, 'suggestion': 'Cap service credits, allow cure periods, and limit credits to a percentage of monthly fees.', 'replacement_category': 'sla'},
    {'pattern': 'uptime commitment', 'rationale': 'Aggressive uptime commitments may be hard to meet.', 'weight': 2, 'default_score': 3, 'suggestion': 'Adjust uptime targets to achievable levels and include maintenance windows and exclusions.', 'replacement_category': 'sla'},
    {'pattern': 'most favored nation', 'rationale': 'MFN clauses force matching best pricing offered to others.', 'weight': 3, 'default_score': 4, 'suggestion': 'Limit MFN to similarly situated customers, term-bound periods, and confidential comparison data.', 'replacement_category': 'pricing'},
    {'pattern': 'exclusive dealing', 'rationale': 'Exclusive dealing can block other partnerships.', 'weight': 3, 'default_score': 3, 'suggestion': 'Restrict exclusivity to defined products or regions and allow exceptions for key partners.', 'replacement_category': 'exclusivity'},
    {'pattern': 'change of control', 'rationale': 'Change-of-control triggers can terminate the agreement.', 'weight': 3, 'default_score': 3, 'suggestion': 'Replace automatic termination with notice and opportunity to cure or maintain assignment rights.', 'replacement_category': 'change_control'},
    {'pattern': 'disclaimer of liability', 'rationale': 'Broad liability disclaimers remove recourse for damages.', 'weight': 3, 'default_score': 4, 'suggestion': 'Add carve-outs for gross negligence, willful misconduct, data loss, and confidentiality breaches.', 'replacement_category': 'disclaimer'},
    {'pattern': 'no consequential damages', 'rationale': 'Excluding consequential damages limits recovery options.', 'weight': 3, 'default_score': 3, 'suggestion': "Carve out consequential damages arising from the other party's breach or data loss.", 'replacement_category': 'disclaimer'},
    {'pattern': 'set-off rights', 'rationale': 'Set-off allows withholding payments owed to you.', 'weight': 2, 'default_score': 3, 'suggestion': 'Limit set-off to undisputed amounts and require prior written notice of intent to offset.', 'replacement_category': 'payments'},
    {'pattern': 'late payment interest', 'rationale': 'Excessive late fees create punitive financial exposure.', 'weight': 2, 'default_score': 3, 'suggestion': 'Cap late fees at statutory limits and include a short grace period for payment processing.', 'replacement_category': 'payments'},
    {'pattern': 'costs and expenses', 'rationale': 'Obligations to cover all costs and expenses add liability.', 'weight': 3, 'default_score': 3, 'suggestion': 'Require pre-approval for expenses, limit to reasonable amounts, and demand documentation.', 'replacement_category': 'payments'},
    {'pattern': 'waives all claims', 'rationale': 'Waiving claims may eliminate legitimate remedies.', 'weight': 4, 'default_score': 4, 'suggestion': 'Narrow the waiver to known claims or limit it to liabilities arising before the agreement date.', 'replacement_category': 'waivers'},
    {'pattern': 'force majeure', 'rationale': 'Force majeure carve-outs can cause performance issues.', 'weight': 2, 'default_score': 2, 'suggestion': 'Clarify notice, mitigation obligations, and rights to suspend or terminate after extended events.', 'replacement_category': 'force_majeure'},
    {'pattern': 'governing language', 'rationale': 'Language precedence may affect interpretation.', 'weight': 1, 'default_score': 2, 'suggestion': 'Confirm the governing language matches the negotiated version or include certified translations.', 'replacement_category': 'language'},
    {'pattern': 'compliance with all laws', 'rationale': 'Broad compliance obligations may be difficult to satisfy.', 'weight': 2, 'default_score': 3, 'suggestion': 'Limit compliance covenant to laws applicable to the services and add knowledge or control qualifiers.', 'replacement_category': 'compliance'},
    {'pattern': 'insurance certificates', 'rationale': 'Extensive insurance requirements increase costs.', 'weight': 2, 'default_score': 3, 'suggestion': 'Align insurance limits with industry standards and allow proof upon reasonable request.', 'replacement_category': 'insurance'},
    {'pattern': 'audit rights', 'rationale': 'Audit rights grant access to records and facilities.', 'weight': 2, 'default_score': 3, 'suggestion': 'Limit audit frequency, require advance notice, and impose confidentiality on audit findings.', 'replacement_category': 'audit'},
    {'pattern': 'escrow account', 'rationale': 'Escrow obligations tie up funds or IP.', 'weight': 2, 'default_score': 3, 'suggestion': 'Clarify release conditions, cost sharing, and the scope of assets placed in escrow.', 'replacement_category': 'escrow'},
    {'pattern': 'liability', 'rationale': 'General liability language can indicate elevated risk.', 'weight': 1, 'default_score': 2, 'suggestion': 'Review surrounding language to ensure liability responsibilities are balanced and clearly defined.', 'replacement_category': 'generic'},
]


# Cache utilities moved to cache_utils.py to use Django cache backend with TTL
# This prevents memory leaks and allows distributed caching with Redis
from .cache_utils import (
    get_cached_chunk_analysis,
    set_cached_chunk_analysis,
    get_cached_focus_analysis,
    set_cached_focus_analysis,
    get_task_status,
    set_task_status,
)

# Enhanced risk detection with improved accuracy
from .risk_detector import (
    detect_enhanced_risks,
    merge_llm_and_heuristic_risks,
    RiskCategory
)
from .improved_prompts import get_improved_system_messages

LLM_AVAILABLE: bool = True
LLM_LAST_ERROR: str = ""


DEFAULT_REPLACEMENTS: Dict[str, str] = {
    'indemnity': (
        'Each party shall indemnify the other solely for third-party claims arising from its own negligence or willful misconduct, '
        'subject to the liability caps set forth in this Agreement.'
    ),
    'liability_cap': (
        'The total aggregate liability of either party shall not exceed the fees paid under this Agreement during the twelve (12) months '
        'preceding the claim, except for liability arising from gross negligence, willful misconduct, or expressly indemnified claims.'
    ),
    'remedies': (
        'If the Services fail to conform, Provider shall promptly remedy the deficiency or provide a mutually agreed service credit; '
        'if unresolved within thirty (30) days, Customer may pursue all remedies available at law or in equity.'
    ),
    'warranty': (
        'Provider warrants that the Services will materially conform to the documentation and be performed in a professional manner, '
        'and Provider will, at its cost, correct any non-conformance reported within the warranty period.'
    ),
    'penalties': (
        'Upon early termination, Customer shall pay Provider undisputed fees earned through the termination date, with no additional '
        'penalties imposed.'
    ),
    'termination': (
        "Either party may terminate this Agreement for convenience upon ninety (90) days' prior written notice, and Provider shall refund "
        'any prepaid, unused fees.'
    ),
    'renewal': (
        'This Agreement shall renew for successive one-year terms only upon mutual written agreement executed at least thirty (30) days '
        'before the current term expires.'
    ),
    'dispute_resolution': (
        'Any dispute shall be resolved through binding arbitration administered by the American Arbitration Association in a mutually '
        'agreed location, with each party bearing its own costs.'
    ),
    'jurisdiction': (
        'The parties consent to the exclusive jurisdiction of the state and federal courts located in a mutually agreed venue, and this '
        'Agreement shall be governed by the laws of that jurisdiction without regard to conflicts principles.'
    ),
    'confidentiality': (
        "Each party shall protect the other's Confidential Information using commercially reasonable care and may disclose it only to "
        'personnel and advisors bound by confidentiality obligations no less protective.'
    ),
    'amendment': (
        'No amendment or modification of this Agreement is effective unless in writing and signed by authorized representatives of both '
        'parties.'
    ),
    'discretion': (
        'Any consent or approval required under this Agreement shall not be unreasonably withheld, conditioned, or delayed, and shall be '
        'made in good faith.'
    ),
    'assignment': (
        "Neither party may assign this Agreement without the other's prior written consent, which shall not be unreasonably withheld; "
        'consent is not required for assignments to affiliates that assume all obligations.'
    ),
    'competition': (
        "During the term, neither party shall directly solicit the other's employees engaged on the Services; general recruitment not "
        'targeted at such employees is permitted.'
    ),
    'ip': (
        'Each party retains ownership of its pre-existing intellectual property. Deliverables created under this Agreement shall be '
        'jointly owned, and each party receives a perpetual, royalty-free license to use them for internal business purposes.'
    ),
    'data_security': (
        'Provider shall implement industry-standard administrative, technical, and physical safeguards to protect Customer Data and shall '
        'notify Customer of any confirmed security incident within forty-eight (48) hours.'
    ),
    'sla': (
        "Provider shall use commercially reasonable efforts to maintain 99.5% monthly uptime, excluding scheduled maintenance with forty-eight "
        "hours' notice, and service credits are capped at twenty percent (20%) of monthly fees."
    ),
    'pricing': (
        'If Provider offers more favorable pricing for materially similar services and volumes, Provider shall notify Customer, and the '
        'parties will negotiate in good faith to adjust pricing accordingly.'
    ),
    'exclusivity': (
        'Customer may engage other suppliers provided Customer meets the minimum purchase commitments set forth in Schedule A.'
    ),
    'change_control': (
        "In the event of a change of control, the affected party shall provide thirty (30) days' prior written notice, and the Agreement "
        'shall remain in effect unless the other party elects to terminate within sixty (60) days.'
    ),
    'disclaimer': (
        'Except for express warranties, neither party makes additional warranties; each party disclaims implied warranties to the extent '
        'permitted by law, without waiving liability for gross negligence or intentional misconduct.'
    ),
    'payments': (
        "Customer may offset undisputed amounts only upon fifteen (15) days' prior written notice, and any late payments accrue interest "
        'at the lesser of one percent (1%) per month or the maximum rate allowed by law.'
    ),
    'waivers': (
        'No waiver of any provision is effective unless in writing and signed by the waiving party, and a waiver of one breach shall not '
        'constitute a waiver of any subsequent breach.'
    ),
    'force_majeure': (
        'Neither party is liable for delays caused by events beyond its reasonable control, provided it promptly notifies the other party, '
        'uses reasonable efforts to mitigate, and resumes performance as soon as practicable.'
    ),
    'language': (
        'This Agreement is drafted in English, which shall control in the event of any translation discrepancies.'
    ),
    'compliance': (
        'Each party shall comply with laws applicable to its performance under this Agreement and promptly notify the other of any '
        'material non-compliance that could impact the Services.'
    ),
    'insurance': (
        'Provider shall maintain insurance coverage consistent with industry standards and, upon request, provide certificates evidencing '
        'such coverage.'
    ),
    'audit': (
        "Customer may audit Provider's relevant records once per year during normal business hours with fifteen (15) days' notice, and all "
        'information obtained shall remain confidential.'
    ),
    'escrow': (
        'If the parties agree to use escrow, they shall establish a mutually acceptable escrow arrangement with release conditions tied to '
        "Provider's insolvency or failure to support the Services."
    ),
    'generic': (
        'Each party shall be responsible for damages caused by its breach of this Agreement, subject to the limitations and exclusions '
        'expressly stated herein.'
    ),
}





def _coerce_risk_score(value: Any, default: int = 3) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        score = default
    return max(1, min(5, score))


def _score_to_label(score: int) -> str:
    return {
        5: 'Critical',
        4: 'High',
        3: 'Medium',
        2: 'Low',
        1: 'Minimal',
    }.get(score, 'Medium')


def _normalize_clause_structure(raw_clause: Dict[str, Any]) -> Dict[str, Any]:
    clause_text = (raw_clause.get('clause_text') or raw_clause.get('clauseText') or '').strip()
    if not clause_text:
        return {}

    risk_score = _coerce_risk_score(
        raw_clause.get('risk_score')
        or raw_clause.get('riskScore')
        or raw_clause.get('score')
        or raw_clause.get('rating')
    )
    risk_level = (raw_clause.get('risk_level') or raw_clause.get('riskLevel') or '').strip()
    if not risk_level:
        risk_level = _score_to_label(risk_score)

    rationale = (raw_clause.get('rationale') or raw_clause.get('reason') or '').strip()
    mitigation = (
        raw_clause.get('mitigation')
        or raw_clause.get('recommendation')
        or raw_clause.get('suggestion')
        or raw_clause.get('proposed_change')
        or raw_clause.get('proposedChange')
        or raw_clause.get('fix')
        or ''
    ).strip()

    replacement_clause = (
        raw_clause.get('replacement_clause')
        or raw_clause.get('replacementClause')
        or raw_clause.get('alternate_clause')
        or raw_clause.get('alternateClause')
        or raw_clause.get('alternative_clause')
        or raw_clause.get('alternativeClause')
        or ''
    ).strip()

    return {
        'clause_text': clause_text,
        'risk_level': risk_level,
        'risk_score': risk_score,
        'rationale': rationale,
        'mitigation': mitigation,
        'replacement_clause': replacement_clause,
        'position': raw_clause.get('position'),  # Preserve position for deduplication
        'confidence': raw_clause.get('confidence'),  # Preserve confidence
        'category': raw_clause.get('category'),  # Preserve category
        'source': raw_clause.get('source'),  # Preserve source
    }


def _order_clauses_by_priority(clauses: List[Dict[str, Any]], full_text: str) -> List[Dict[str, Any]]:
    if not clauses:
        return clauses

    def clause_position(text: str) -> int:
        if not full_text:
            return 0
        idx = full_text.find(text)
        return idx if idx >= 0 else len(full_text)

    return sorted(
        clauses,
        key=lambda item: (
            -int(item.get('risk_score', 3) or 3),
            clause_position(item.get('clause_text', '')),
        )
    )


def _fallback_risk_clauses(full_text: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Enhanced heuristic scan using contextual pattern matching."""
    if not full_text:
        return []

    # Use enhanced risk detector with context awareness
    detected_risks = detect_enhanced_risks(full_text, max_clauses=limit)
    
    # Convert to expected format and add replacement clauses
    enhanced_clauses = []
    for risk in detected_risks:
        category = risk.get('category', 'generic')
        replacement_clause = DEFAULT_REPLACEMENTS.get(category, DEFAULT_REPLACEMENTS['generic'])
        
        enhanced_clauses.append({
            'clause_text': risk['clause_text'],
            'risk_level': risk['risk_level'],
            'risk_score': risk['risk_score'],
            'rationale': risk['rationale'],
            'mitigation': risk['mitigation'],
            'replacement_clause': replacement_clause,
            'confidence': risk.get('confidence', 0.7),
            'category': category,
        })
    
    # Fallback to old method if enhanced detection found nothing
    if not enhanced_clauses:
        logger.warning("Enhanced detection found no risks, using legacy keyword matching")
        lowered = full_text.lower()
        clauses: List[Dict[str, Any]] = []

        for keyword_info in RISK_KEYWORDS[:20]:  # Limit to top 20 patterns
            keyword = keyword_info['pattern']
            matches = list(re.finditer(re.escape(keyword), lowered))
            if matches:
                match = matches[0]  # Just take first match
                start = max(0, match.start() - 220)
                end = min(len(full_text), match.end() + 220)
                snippet = full_text[start:end].strip()
                if snippet:
                    clauses.append({
                        'clause_text': snippet,
                        'risk_level': _score_to_label(keyword_info.get('default_score', 3)),
                        'risk_score': keyword_info.get('default_score', 3),
                        'rationale': keyword_info['rationale'],
                        'mitigation': keyword_info.get('suggestion', ''),
                        'replacement_clause': DEFAULT_REPLACEMENTS.get(
                            keyword_info.get('replacement_category', 'generic'),
                            DEFAULT_REPLACEMENTS['generic']
                        ),
                    })
                if len(clauses) >= limit:
                    break
        return clauses
    
    return enhanced_clauses


def _keyword_score(text: str) -> int:
    if not text:
        return 0
    lowered = text.lower()
    score = 0
    for keyword_info in RISK_KEYWORDS:
        pattern = keyword_info['pattern']
        weight = keyword_info.get('weight', 1)
        score += lowered.count(pattern) * weight
    return score


def _extract_keyword_sentences(full_text: str, max_sentences: int = 12) -> List[str]:
    if not full_text:
        return []

    sentences = re.split(r'(?<=[.!?])\s+', full_text)
    scored: List[Tuple[int, int, str]] = []

    for idx, sentence in enumerate(sentences):
        cleaned = sentence.strip()
        if not cleaned:
            continue
        score = _keyword_score(cleaned)
        if score > 0:
            scored.append((score, idx, cleaned))

    if not scored:
        return []

    scored.sort(key=lambda item: (-item[0], item[1]))
    top_sentences = [item[2] for item in scored[:max_sentences]]
    return top_sentences


def _chunk_document(full_text: str, chunk_size: int = 2500, overlap: int = 300) -> List[Dict[str, Any]]:
    """Split document into overlapping chunks to keep model prompts small."""
    if not full_text:
        return []

    if len(full_text) <= chunk_size:
        return [{'text': full_text, 'start': 0, 'end': len(full_text)}]

    chunks: List[Dict[str, Any]] = []
    step = max(chunk_size - overlap, 900)
    position = 0

    while position < len(full_text):
        end = min(len(full_text), position + chunk_size)
        chunk_text = full_text[position:end]
        chunks.append({'text': chunk_text, 'start': position, 'end': end})
        if end == len(full_text):
            break
        position += step

    return chunks


def _dedupe_clauses(clauses: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    """Remove duplicate clause entries while preserving order."""
    seen: Dict[str, int] = {}
    deduped: List[Dict[str, Any]] = []

    for clause in clauses:
        normalized_clause = _normalize_clause_structure(clause)
        clause_text = normalized_clause.get('clause_text')
        if not clause_text:
            continue
        
        # Create fingerprint focusing on significant words
        words = clause_text.lower().split()
        significant_words = [w for w in words if len(w) > 3][:25]
        fingerprint = ' '.join(significant_words)
        
        # Check fingerprint first (fast)
        if fingerprint in seen:
            existing_index = seen[fingerprint]
            existing_clause = deduped[existing_index]
            # Keep higher risk score
            if normalized_clause.get('risk_score', 0) > existing_clause.get('risk_score', 0):
                deduped[existing_index] = normalized_clause
            else:
                # Merge missing attributes
                for key in ('risk_level', 'risk_score', 'rationale', 'mitigation', 'replacement_clause', 'confidence'):
                    if not existing_clause.get(key) and normalized_clause.get(key):
                        existing_clause[key] = normalized_clause.get(key)
            continue
        
        # Check for position overlap if available
        is_duplicate = False
        clause_pos = normalized_clause.get('position')
        
        if clause_pos:
            for i, existing_clause in enumerate(deduped):
                existing_pos = existing_clause.get('position')
                
                # Check document position overlap
                if existing_pos:
                    overlap_start = max(clause_pos[0], existing_pos[0])
                    overlap_end = min(clause_pos[1], existing_pos[1])
                    overlap = max(0, overlap_end - overlap_start)
                    clause_length = clause_pos[1] - clause_pos[0]
                    existing_length = existing_pos[1] - existing_pos[0]
                    
                    # If >50% overlap of either clause, it's same clause
                    if clause_length > 0 and (overlap > clause_length * 0.5 or overlap > existing_length * 0.5):
                        is_duplicate = True
                        # Keep higher risk score
                        if normalized_clause.get('risk_score', 0) > existing_clause.get('risk_score', 0):
                            deduped[i] = normalized_clause
                        break
        
        if is_duplicate:
            continue
        
        seen[fingerprint] = len(deduped)
        deduped.append(normalized_clause)
        
        if len(deduped) >= limit:
            break

    return deduped


def _generate_comprehensive_summary(full_text: str, doc_type: str, llm, doc_type_name: str, use_llm: bool = True) -> Dict[str, Any]:
    """Generate detailed legal document summary with structured sections and plain language explanations.
    
    Args:
        full_text: Full document text
        doc_type: Document type identifier
        llm: LangChain LLM instance
        doc_type_name: Human-readable document type name
        use_llm: Whether to try LLM first (fallback to regex if quota exceeded)
        
    Returns:
        Comprehensive summary dictionary with structured information
    """
    
    # If LLM is disabled or unavailable, use regex extraction directly
    if not use_llm or not llm:
        logger.info("Using regex-based comprehensive summary (LLM disabled)")
        return _generate_comprehensive_summary_from_analysis(
            full_text=full_text,
            doc_type=doc_type,
            doc_type_name=doc_type_name,
            chunk_results=[],
            deduped_clauses=[]
        )
    
    try:
        from langchain_core.prompts import ChatPromptTemplate
        from pydantic import BaseModel, Field
        from typing import Optional
        
        class PartyInfo(BaseModel):
            name: str = Field(..., description="Full legal name of the party")
            role: str = Field(..., description="Role in document (e.g., Employer, Tenant, Service Provider, Disclosing Party)")
            simple_explanation: Optional[str] = Field(None, description="Plain language explanation of what this party does in this agreement")
        
        class FinancialTerm(BaseModel):
            item: str = Field(..., description="What the payment/amount is for")
            amount: str = Field(..., description="The specific amount, rate, or value")
            simple_explanation: Optional[str] = Field(None, description="Plain language explanation")
        
        class TerminationInfo(BaseModel):
            duration: str = Field(..., description="How long the agreement lasts")
            renewal_terms: Optional[str] = Field(None, description="How/when it renews")
            termination_process: str = Field(..., description="How to end the agreement")
            notice_period: Optional[str] = Field(None, description="Required notice to terminate")
            simple_explanation: str = Field(..., description="Plain language explanation of term and exit options")
        
        class LegalTermExplanation(BaseModel):
            term: str = Field(..., description="Complex legal term or phrase")
            meaning: str = Field(..., description="Simple, everyday language explanation")
        
        class ComprehensiveSummary(BaseModel):
            document_type: str = Field(..., description="Specific type of legal document")
            execution_date: Optional[str] = Field(None, description="Date document was/will be signed")
            parties: List[PartyInfo] = Field(..., description="All parties involved with roles")
            purpose: str = Field(..., description="Core reason this document exists (2-3 sentences max)")
            key_obligations: Dict[str, str] = Field(..., description="Map of party name to their main responsibilities")
            financial_terms: List[FinancialTerm] = Field(default_factory=list, description="Payment amounts, fees, compensation")
            term_and_termination: TerminationInfo = Field(..., description="Duration and how to end the agreement")
            compliance_requirements: Optional[List[str]] = Field(default_factory=list, description="Legal compliance obligations")
            important_deadlines: Optional[List[str]] = Field(default_factory=list, description="Time-sensitive obligations")
            attachments_mentioned: Optional[List[str]] = Field(default_factory=list, description="Schedules, exhibits, annexures referenced")
            legal_terms_explained: List[LegalTermExplanation] = Field(default_factory=list, description="Complex legal terms with plain language meanings")
            executive_summary: str = Field(..., description="2-3 paragraph plain language overview suitable for non-lawyers (150-250 words)")
        
        summary_prompt = ChatPromptTemplate.from_messages([
            (
                'system',
                f"You are an expert legal document analyst specializing in {doc_type_name}. "
                "Your role is to create comprehensive, structured summaries that make legal documents "
                "accessible to non-lawyers while maintaining accuracy.\\n\\n"
                "CRITICAL INSTRUCTIONS:\\n"
                "1. Extract ALL key information systematically\\n"
                "2. For complex legal terms, provide plain language explanations\\n"
                "3. Use everyday language in 'simple_explanation' fields\\n"
                "4. Be specific with amounts, dates, timeframes\\n"
                "5. Focus on practical implications for each party\\n"
                "6. The executive_summary should be readable by anyone without legal training\\n\\n"
                "PLAIN LANGUAGE EXAMPLES:\\n"
                "❌ 'Indemnification obligation' → ✅ 'If something goes wrong because of Party A, they must pay for any resulting costs'\\n"
                "❌ 'Force majeure provision' → ✅ 'If unexpected events like natural disasters happen, neither party is blamed'\\n"
                "❌ 'Liquidated damages' → ✅ 'Pre-agreed penalty amount if someone breaks the contract'\\n"
                "❌ 'Representations and warranties' → ✅ 'Promises and guarantees each party is making'\\n\\n"
                "Think of this as explaining the document to a friend who isn't a lawyer."
            ),
            (
                'human',
                "LEGAL DOCUMENT TO ANALYZE:\\n\\n{document_text}\\n\\n"
                "ANALYSIS REQUIREMENTS:\\n\\n"
                "1. DOCUMENT IDENTIFICATION\\n"
                "   - What type of document is this exactly?\\n"
                "   - When was/will it be signed? (check for execution date, effective date)\\n"
                "   - Who are ALL the parties? (get full names and their roles)\\n\\n"
                "2. PURPOSE\\n"
                "   - Why does this document exist?\\n"
                "   - What relationship/transaction does it govern?\\n"
                "   - Write in simple language: 'This agreement allows Party A to... while Party B will...'\\n\\n"
                "3. KEY RIGHTS & OBLIGATIONS\\n"
                "   - For EACH party, what must they do?\\n"
                "   - What are they NOT allowed to do?\\n"
                "   - What do they receive in return?\\n"
                "   - Be specific about deliverables, services, restrictions\\n\\n"
                "4. FINANCIAL TERMS\\n"
                "   - All payment amounts (salary, rent, fees, deposits)\\n"
                "   - When payments are due\\n"
                "   - Penalties, bonuses, incentives\\n"
                "   - Any caps or limits\\n\\n"
                "5. TERM & TERMINATION\\n"
                "   - How long does this last?\\n"
                "   - Does it auto-renew?\\n"
                "   - How can each party get out of it?\\n"
                "   - What notice is required?\\n"
                "   - What happens after termination?\\n\\n"
                "6. COMPLIANCE & LEGAL OBLIGATIONS\\n"
                "   - Any laws, regulations, or licenses mentioned\\n"
                "   - Data protection, privacy requirements\\n"
                "   - Insurance, bonding, security requirements\\n"
                "   - Audit rights, reporting obligations\\n\\n"
                "7. IMPORTANT DEADLINES\\n"
                "   - Payment due dates\\n"
                "   - Delivery schedules\\n"
                "   - Reporting timelines\\n"
                "   - Review or renewal dates\\n\\n"
                "8. ATTACHMENTS/SCHEDULES\\n"
                "   - List any annexures, exhibits, SOWs, schedules mentioned\\n\\n"
                "9. COMPLEX LEGAL TERMS\\n"
                "   - Identify 5-8 legal terms that a non-lawyer might not understand\\n"
                "   - Provide simple, everyday language explanations\\n"
                "   - Examples: indemnification, force majeure, severability, liquidated damages, etc.\\n\\n"
                "10. EXECUTIVE SUMMARY\\n"
                "   - Write 2-3 paragraphs in plain language\\n"
                "   - Should be understandable by someone with no legal training\\n"
                "   - Cover: what this is, who's involved, what happens, key numbers, how long it lasts\\n"
                "   - Use analogies or everyday examples if helpful\\n"
                "   - 150-250 words\\n\\n"
                "REMEMBER: Your goal is to make this legal document fully understandable to a non-lawyer "
                "while capturing all essential information accurately."
            )
        ])
        
        # Configure LLM with conservative settings to reduce None returns
        import time
        from langchain_google_genai import ChatGoogleGenerativeAI
        
        # Use gemini-2.5-flash for comprehensive summary
        model_for_summary = _get_llm_model_name()  # Consistent with main config
        
        # Fallback to base model if primary fails
        fallback_models = [
            "gemini-1.5-flash"  # Fallback option
        ]
        
        logger.info(f"Using {model_for_summary} for comprehensive summary (optimized for quota efficiency)")
        
        # Use a dedicated LLM instance with optimized settings for structured output
        # CRITICAL: Do NOT use response_mime_type with with_structured_output() - they conflict!
        summary_llm = ChatGoogleGenerativeAI(
            model=model_for_summary,
            temperature=0.2,  # Slightly higher for Flash (better quality)
            max_output_tokens=2048,  # Standard limit for most models
            google_api_key=settings.GEMINI_API_KEY,
            max_retries=1,  # Reduced retries to avoid quota waste
            request_timeout=60,  # Standard timeout
            # DO NOT set response_mime_type - it conflicts with with_structured_output()
            # DO NOT set candidate_count=1 - causes empty responses with structured output
        )
        
        structured_summary_llm = summary_llm.with_structured_output(ComprehensiveSummary)
        chain = summary_prompt | structured_summary_llm
        
        # Limit document text to avoid token limits (use first 6000 chars for more reliable processing)
        truncated_text = full_text[:6000]  # Reduced from 8000 for better reliability
        if len(full_text) > 6000:
            # Add context about truncation
            truncated_text += "\\n\\n[Document continues for " + str(len(full_text) - 6000) + " more characters...]\\n\\nNote: Analyze the provided excerpt and extract all available information."
        
        logger.info(f"Generating comprehensive {doc_type_name} summary using LLM (text length: {len(truncated_text)} chars)...")
        
        # Invoke with retry logic and model fallback
        result = None
        max_attempts = 2  # Reduced to 2 since we have model fallback
        last_error = None
        
        # Try primary model, then fallback models
        models_to_try = [model_for_summary] + fallback_models
        
        for model_name in models_to_try:
            logger.info(f"Trying model: {model_name}")
            
            # Create LLM instance for this model
            try:
                # Adjust parameters based on model type
                is_pro = "pro" in model_name
                is_exp = "exp" in model_name
                
                current_llm = ChatGoogleGenerativeAI(
                    model=model_name,
                    temperature=0.2,  # Consistent across models
                    max_output_tokens=2048,  # Standard limit
                    google_api_key=settings.GEMINI_API_KEY,
                    max_retries=1,  # Single retry to save quota
                    request_timeout=75 if is_pro else 60,  # Pro gets slightly more time
                )
                
                current_structured_llm = current_llm.with_structured_output(ComprehensiveSummary)
                current_chain = summary_prompt | current_structured_llm
                
            except Exception as model_init_error:
                logger.warning(f"Failed to initialize {model_name}: {model_init_error}")
                last_error = model_init_error
                continue
            for attempt in range(max_attempts):
                try:
                    logger.info(f"Model {model_name}, attempt {attempt + 1}/{max_attempts}...")
                    
                    result = current_chain.invoke(
                        {'document_text': truncated_text},
                        config={"max_retries": 0, "request_timeout": 60}  # No retries here, we handle it ourselves
                    )
                    
                    # Check immediately if result is None
                    if result is None:
                        logger.warning(f"{model_name} returned None on attempt {attempt + 1}")
                        if attempt < max_attempts - 1:
                            wait_time = 2  # Fixed 2 second wait
                            logger.info(f"Retrying in {wait_time} seconds...")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.warning(f"{model_name} returned None after {max_attempts} attempts, trying next model")
                            last_error = ValueError(f"{model_name} returned None")
                            break  # Try next model
                    
                    # Validate result has expected structure
                    if not hasattr(result, 'model_dump') and not hasattr(result, 'dict') and not isinstance(result, dict):
                        logger.warning(f"{model_name} returned unexpected type: {type(result)}")
                        if attempt < max_attempts - 1:
                            time.sleep(2)
                            continue
                        else:
                            logger.warning(f"{model_name} returned wrong type after {max_attempts} attempts, trying next model")
                            last_error = ValueError(f"Unexpected type: {type(result)}")
                            break  # Try next model
                    
                    # Success - we got a valid result!
                    logger.info(f"✅ {model_name} returned valid result on attempt {attempt + 1}")
                    break  # Break attempt loop
                    
                except Exception as invoke_exc:
                    error_msg = str(invoke_exc)
                    logger.warning(f"{model_name} attempt {attempt + 1} failed: {error_msg}")
                    last_error = invoke_exc
                    
                    # Check for quota/rate limit errors
                    is_quota = any(indicator in error_msg.lower() for indicator in 
                                  ['quota', 'rate limit', '429', 'resource exhausted', 'quota exceeded'])
                    
                    if is_quota:
                        logger.warning(f"Quota/rate limit detected: {error_msg}")
                        raise  # Don't retry on quota issues, trigger fallback immediately
                    
                    # For other errors, retry if attempts remain
                    if attempt < max_attempts - 1:
                        wait_time = 2
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        logger.warning(f"{model_name} failed after {max_attempts} attempts, trying next model")
                        break  # Try next model
            
            # Check if we got a valid result from this model
            if result is not None:
                logger.info(f"✅ Successfully got result from {model_name}")
                break  # Break model loop - we're done!
        
        # After trying all models, check if we got a result
        if result is None:
            error_message = f"All models failed to generate output. Last error: {last_error}"
            logger.error(error_message)
            raise ValueError(error_message)
        
        logger.info(f"✅ LLM returned result type: {type(result)}")
        
        # Final validation that result is not None
        if result is None:
            logger.error("LLM returned None after all retry attempts - falling back to regex extraction")
            raise ValueError("LLM returned None after retry logic - likely API quota or persistent connection issue")
        
        # Extract data from result with comprehensive error handling
        try:
            if hasattr(result, 'model_dump'):
                summary_dict = result.model_dump()
                logger.info("Extracted data using model_dump()")
            elif hasattr(result, 'dict'):
                summary_dict = result.dict()
                logger.info("Extracted data using dict()")
            elif isinstance(result, dict):
                summary_dict = result
                logger.info("Result is already a dict")
            else:
                # Last resort - try to convert to dict
                summary_dict = dict(result) if result is not None else {}
                logger.warning(f"Converted result to dict using dict() constructor")
                
            # Validate we got a non-empty dictionary
            if not summary_dict:
                logger.warning("Extracted summary_dict is empty")
                raise ValueError("Extracted empty dictionary from LLM result")
                
        except (TypeError, ValueError, AttributeError) as extract_error:
            logger.error(f"Failed to extract data from LLM result: {extract_error}", exc_info=True)
            raise ValueError(f"Failed to extract data from LLM result: {extract_error}")
        
        # Ensure all required fields exist with defaults
        summary_dict.setdefault('document_type', doc_type_name)
        summary_dict.setdefault('parties', [])
        summary_dict.setdefault('purpose', 'Purpose not extracted')
        summary_dict.setdefault('key_obligations', {})
        summary_dict.setdefault('financial_terms', [])
        summary_dict.setdefault('legal_terms_explained', [])
        summary_dict.setdefault('compliance_requirements', [])
        summary_dict.setdefault('important_deadlines', [])
        summary_dict.setdefault('attachments_mentioned', [])
        
        if not summary_dict.get('term_and_termination'):
            summary_dict['term_and_termination'] = {
                'duration': 'Not specified',
                'termination_process': 'Not specified',
                'simple_explanation': 'Unable to extract termination details'
            }
        
        if not summary_dict.get('executive_summary'):
            summary_dict['executive_summary'] = textwrap.shorten(full_text, width=250, placeholder='...')
        
        logger.info(f"✅ Comprehensive summary generated: {len(summary_dict.get('executive_summary', ''))} chars, "
                   f"{len(summary_dict.get('parties', []))} parties, "
                   f"{len(summary_dict.get('legal_terms_explained', []))} terms explained")
        
        return summary_dict
        
    except Exception as exc:
        error_msg = str(exc)
        # Check if this is a quota/rate limit issue
        is_quota_issue = any(indicator in error_msg.lower() for indicator in 
                            ['quota', 'rate limit', '429', 'resource exhausted', 'quota exceeded'])
        
        if is_quota_issue:
            logger.warning(f"LLM quota exceeded for comprehensive summary, using regex fallback: {error_msg}")
        else:
            logger.error(f"Comprehensive summary LLM generation failed: {exc}", exc_info=True)
        
        # Fallback to regex-based extraction (more intelligent than basic)
        logger.info("Falling back to regex-based comprehensive summary extraction")
        try:
            return _generate_comprehensive_summary_from_analysis(
                full_text=full_text,
                doc_type=doc_type,
                doc_type_name=doc_type_name,
                chunk_results=[],
                deduped_clauses=[]
            )
        except Exception as fallback_exc:
            logger.error(f"Regex fallback also failed: {fallback_exc}", exc_info=True)
            # Final fallback to minimal summary
            return {
                'document_type': doc_type_name,
                'executive_summary': textwrap.shorten(full_text, width=500, placeholder='...'),
                'parties': [],
                'purpose': 'Unable to generate detailed analysis. Please review document manually.',
                'key_obligations': {},
                'financial_terms': [],
                'term_and_termination': {
                    'duration': 'Not specified',
                    'termination_process': 'Not specified',
                    'simple_explanation': 'Unable to extract termination details'
                },
                'legal_terms_explained': [],
            }


def _generate_comprehensive_summary_from_analysis(
    full_text: str, 
    doc_type: str, 
    doc_type_name: str,
    chunk_results: List[Dict[str, Any]],
    deduped_clauses: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Generate comprehensive summary by intelligently extracting from existing text and analysis.
    This avoids making another expensive LLM call.
    """
    import re
    from datetime import datetime
    
    try:
        # Extract dates
        date_patterns = [
            r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
            r'\b\d{4}[-/]\d{2}[-/]\d{2}\b'
        ]
        dates_found = []
        for pattern in date_patterns:
            dates_found.extend(re.findall(pattern, full_text[:2000], re.IGNORECASE))
        execution_date = dates_found[0] if dates_found else None
        
        # Extract parties (look for common patterns)
        party_patterns = [
            r'between\s+([A-Z][A-Za-z\s&,\.]+?)\s+(?:and|&)\s+([A-Z][A-Za-z\s&,\.]+?)(?:\s+dated|\s+effective|\()',
            r'(?:Employer|Client|Lessor|Disclosing Party|Provider|Company):\s*([A-Z][A-Za-z\s&,\.]+?)(?:\n|;|,)',
            r'(?:Employee|Contractor|Lessee|Receiving Party|Customer):\s*([A-Z][A-Za-z\s&,\.]+?)(?:\n|;|,)'
        ]
        parties = []
        for pattern in party_patterns:
            matches = re.findall(pattern, full_text[:3000], re.IGNORECASE)
            if matches:
                if isinstance(matches[0], tuple):
                    for party in matches[0]:
                        if party and len(party) < 100:
                            parties.append({'name': party.strip(), 'role': 'Party'})
                else:
                    for party in matches:
                        if party and len(party) < 100:
                            parties.append({'name': party.strip(), 'role': 'Party'})
                if parties:
                    break
        
        # Extract financial terms
        financial_terms = []
        money_patterns = [
            r'\$[\d,]+(?:\.\d{2})?(?:\s+(?:per|/)\s+\w+)?',
            r'(?:salary|compensation|rent|fee|payment)(?:\s+of)?\s*:?\s*\$?[\d,]+(?:\.\d{2})?',
        ]
        for pattern in money_patterns:
            amounts = re.findall(pattern, full_text[:5000], re.IGNORECASE)
            for amount in amounts[:5]:
                financial_terms.append({
                    'item': 'Payment',
                    'amount': amount.strip()
                })
        
        # Extract term/duration
        term_patterns = [
            r'(?:term|duration|period)(?:\s+of)?:?\s*(\d+\s+(?:days?|months?|years?))',
            r'for\s+a\s+(?:term|period)\s+of\s+(\d+\s+(?:days?|months?|years?))',
        ]
        duration = None
        for pattern in term_patterns:
            match = re.search(pattern, full_text[:5000], re.IGNORECASE)
            if match:
                duration = match.group(1)
                break
        
        # Extract termination notice
        notice_patterns = [
            r'(\d+\s+days?)(?:\s+(?:prior|advance))?\s+(?:written\s+)?notice',
            r'notice\s+of\s+(\d+\s+days?)',
        ]
        notice_period = None
        for pattern in notice_patterns:
            match = re.search(pattern, full_text[:5000], re.IGNORECASE)
            if match:
                notice_period = match.group(1)
                break
        
        # Extract legal terms from risky clauses
        legal_terms = []
        legal_term_keywords = [
            ('indemnification', 'If something goes wrong because of one party, they must pay for any resulting costs'),
            ('force majeure', 'If unexpected events like natural disasters happen, neither party is blamed for delays'),
            ('liquidated damages', 'Pre-agreed penalty amount if someone breaks the contract'),
            ('severability', 'If one part of the contract is invalid, the rest still applies'),
            ('governing law', 'Which state or country\'s laws control how disputes are resolved'),
            ('confidentiality', 'Requirement to keep sensitive information private'),
            ('non-compete', 'Restriction preventing you from working for competitors'),
            ('intellectual property', 'Ownership of ideas, inventions, and creative work'),
            ('warranty', 'Promise or guarantee that something is true or will work as stated'),
            ('liability', 'Legal responsibility for damages or losses')
        ]
        
        full_text_lower = full_text.lower()
        for term, meaning in legal_term_keywords:
            if term in full_text_lower:
                legal_terms.append({'term': term.title(), 'meaning': meaning})
        
        # Create executive summary from chunk summaries
        chunk_summaries = [result.get('summary', '') for result in chunk_results if result.get('summary')]
        executive_summary = ' '.join(chunk_summaries[:3])[:250]
        
        if not executive_summary:
            executive_summary = textwrap.shorten(full_text, width=250, placeholder='...')
        
        # Build comprehensive summary
        return {
            'document_type': doc_type_name,
            'execution_date': execution_date,
            'parties': parties[:5],  # Limit to first 5
            'purpose': f"This {doc_type_name} establishes the terms and conditions between the parties.",
            'key_obligations': {},
            'financial_terms': financial_terms[:5],
            'term_and_termination': {
                'duration': duration or 'Not specified',
                'renewal_terms': None,
                'termination_process': f"Either party may terminate with {notice_period} notice" if notice_period else 'Not specified',
                'notice_period': notice_period,
                'simple_explanation': f"This agreement lasts for {duration}. You can exit by giving {notice_period} written notice." if duration and notice_period else "Review document for specific term and termination details."
            },
            'compliance_requirements': [],
            'important_deadlines': [],
            'attachments_mentioned': [],
            'legal_terms_explained': legal_terms[:8],
            'executive_summary': executive_summary,
        }
        
    except Exception as exc:
        logger.error(f"Failed to extract comprehensive summary from analysis: {exc}", exc_info=True)
        return {
            'document_type': doc_type_name,
            'executive_summary': textwrap.shorten(full_text, width=250, placeholder='...'),
            'parties': [],
            'purpose': 'Unable to extract details automatically.',
            'key_obligations': {},
            'financial_terms': [],
            'term_and_termination': {
                'duration': 'Not specified',
                'termination_process': 'Not specified',
                'simple_explanation': 'Review document for details'
            },
            'legal_terms_explained': [],
        }


def _merge_summaries(parts: List[str], max_chars: int = 900) -> str:
    """Combine chunk summaries into a concise overview."""
    cleaned = [part.strip() for part in parts if part and part.strip()]
    if not cleaned:
        return ''

    combined = ' '.join(cleaned)
    if len(combined) <= max_chars:
        return combined

    return textwrap.shorten(combined, width=max_chars, placeholder='…')


def _analyze_chunk_with_llm(
    chunk: Dict[str, Any],
    idx: int,
    prompt,
    structured_llm,
) -> Dict[str, Any]:
    """Invoke Gemini on a single chunk with caching and fallbacks."""
    global LLM_AVAILABLE, LLM_LAST_ERROR

    if not LLM_AVAILABLE:
        return {
            'summary': textwrap.shorten(chunk['text'].replace('\n', ' '), width=260, placeholder='…'),
            'high_risk_clauses': _fallback_risk_clauses(chunk['text'], limit=3),
        }

    chunk_text = chunk['text']
    
    # Check cache using Django cache backend
    cached_result = get_cached_chunk_analysis(chunk_text)
    if cached_result:
        return cached_result

    try:
        chain = prompt | structured_llm
        result = chain.invoke({
            'chunk_index': idx + 1,
            'chunk_length': len(chunk_text),
            'chunk_text': chunk_text,
        })

        if hasattr(result, 'model_dump'):
            data = result.model_dump()
        elif hasattr(result, 'dict'):
            data = result.dict()
        else:
            data = dict(result or {})

        summary_text = (data.get('summary') or '').strip()

        chunk_clauses: List[Dict[str, Any]] = []
        for clause in data.get('high_risk_clauses') or []:
            if hasattr(clause, 'model_dump'):
                clause = clause.model_dump()
            elif hasattr(clause, 'dict'):
                clause = clause.dict()
            normalized = _normalize_clause_structure(clause)
            if normalized:
                chunk_clauses.append(normalized)

        if not chunk_clauses:
            chunk_clauses = _fallback_risk_clauses(chunk_text, limit=3)

        chunk_result = {
            'summary': summary_text,
            'high_risk_clauses': chunk_clauses,
        }

        set_cached_chunk_analysis(chunk_text, chunk_result)
        return chunk_result

    except Exception as exc:  # pylint: disable=broad-except
        error_message = str(exc)
        logger.warning("Chunk %s analysis failed, using heuristic fallback: %s", idx + 1, error_message)

        if (GoogleModelNotFound and isinstance(exc, GoogleModelNotFound)) or 'NotFound' in error_message:
            LLM_AVAILABLE = False
            LLM_LAST_ERROR = error_message
            logger.error(
                "Disabling Gemini LLM due to NotFound error. Configure settings.GEMINI_MODEL with an available model name.")

        fallback_result = {
            'summary': textwrap.shorten(chunk_text.replace('\n', ' '), width=320, placeholder='…'),
            'high_risk_clauses': _fallback_risk_clauses(chunk_text, limit=3),
        }
        set_cached_chunk_analysis(chunk_text, fallback_result)
        return fallback_result


def _analyze_focus_snippets(
    snippets: List[str],
    structured_llm,
    doc_type: str = 'generic',
) -> Dict[str, Any]:
    global LLM_AVAILABLE, LLM_LAST_ERROR

    if not snippets:
        return {'summary': '', 'high_risk_clauses': []}

    if not LLM_AVAILABLE:
        focus_text = "\n---\n".join(snippets)
        return {
            'summary': textwrap.shorten(focus_text.replace('\n', ' '), width=360, placeholder='…'),
            'high_risk_clauses': _fallback_risk_clauses(focus_text, limit=4),
        }

    from langchain_core.prompts import ChatPromptTemplate
    from .document_classifier import get_type_specific_system_prompt, get_type_specific_examples, DOCUMENT_TYPES
    from .enhanced_risk_patterns import (
        get_enhanced_risk_patterns_by_type,
        generate_dynamic_alternative_clause,
        get_type_specific_mitigation_strategies
    )

    focus_text = "\n---\n".join(snippets)
    if len(focus_text) > 6000:
        focus_text = focus_text[:6000]

    # Check cache using Django cache backend
    cached_result = get_cached_focus_analysis(focus_text)
    if cached_result:
        return cached_result

    # Get type-specific prompts for focused analysis
    type_specific_prompt = get_type_specific_system_prompt(doc_type)
    type_specific_examples = get_type_specific_examples(doc_type)
    doc_type_name = DOCUMENT_TYPES.get(doc_type, {}).get('name', 'General Agreement')
    
    # Get enhanced risk patterns and mitigation strategies for this document type
    risk_patterns = get_enhanced_risk_patterns_by_type(doc_type)
    mitigation_strategies = get_type_specific_mitigation_strategies(doc_type)
    
    # Build context about common risk patterns for this document type
    pattern_context = ""
    if risk_patterns:
        pattern_examples = []
        for risk_category, pattern_info in list(risk_patterns.items())[:3]:  # Show top 3 patterns
            pattern_examples.append(
                f"• {pattern_info['context']} (Severity: {pattern_info['severity']}/5)\n"
                f"  Solution: {pattern_info['solution_template'][:100]}..."
            )
        if pattern_examples:
            pattern_context = (
                f"\n\nCOMMON {doc_type_name.upper()} RISKS TO WATCH FOR:\n" + 
                "\n".join(pattern_examples)
            )
    
    # Get improved prompts and enhance with type-specific system prompt and patterns
    improved_prompts = get_improved_system_messages()
    improved_prompts['system_prompt'] = type_specific_prompt + pattern_context
    
    # Build example messages from type-specific examples
    example_messages = []
    if type_specific_examples and len(type_specific_examples) > 0:
        example = type_specific_examples[0]
        example_messages.extend([
            (
                'human',
                f"Example excerpt:\n'{example['clause_text'][:100]}...'"
            ),
            (
                'ai',
                '{{"summary": "' + example['rationale'] + '", "high_risk_clauses": ['
                '{{"clause_text": "' + example['clause_text'][:80] + '...", '
                f'"risk_score": {example["risk_score"]}, "risk_level": "{example["risk_level"]}", '
                '"rationale": "' + example['rationale'][:45] + '", '
                '"mitigation": "' + example['mitigation'][:45] + '", '
                '"replacement_clause": "' + example['replacement_clause'][:100] + '..."}}]}}'
            )
        ])
    else:
        example_messages.extend([
            (
                'human',
                "Example excerpts:\n1) 'Vendor shall indemnify and hold harmless Customer from any and all losses.'\n2) 'This agreement renews automatically for successive one-year terms unless terminated 90 days before renewal.'"
            ),
            (
                'ai',
                '{{"summary": "Clauses show broad indemnity and automatic renewal obligations.", "high_risk_clauses": ['
                '{{"clause_text": "Vendor shall indemnify and hold harmless Customer from any and all losses.", "risk_score": 5, "risk_level": "Critical", "rationale": "Broad indemnity shifts unlimited liability.", '
                '"mitigation": "Require mutual indemnity limited to losses caused by each party and cap total exposure.", '
                '"replacement_clause": "Each party shall indemnify the other solely for third-party claims arising from its own negligence or willful misconduct, subject to the liability caps set forth herein."}}, '
                '{{"clause_text": "This agreement renews automatically for successive one-year terms unless terminated 90 days before renewal.", "risk_score": 4, "risk_level": "High", "rationale": "Automatic renewal requires long notice to avoid extension.", '
                '"mitigation": "Reduce the notice period and require explicit written confirmation before renewal.", '
                '"replacement_clause": "This Agreement may renew for additional one-year terms only upon the parties\' mutual written agreement executed at least thirty (30) days before the then-current term expires."}}]}}'
            )
        ])
    
    focus_prompt = ChatPromptTemplate.from_messages([
        (
            'system',
            improved_prompts['system_prompt']
        ),
        (
            'system',
            'Return a single JSON object that conforms to the schema. Do not add explanations, code fences, or any surrounding text.'
        ),
        (
            'system',
            improved_prompts['focus_instructions']
        ),
        (
            'system',
            'Assign risk_score from 1 (minimal) to 5 (critical) based on actual impact.'
        ),
        (
            'system',
            f'For every risky clause, provide SPECIFIC mitigation tailored to {doc_type_name}. General strategy: {mitigation_strategies.get("general", "Negotiate fair and balanced terms.")}'
        ),
        (
            'system',
            'Mitigation must be ACTIONABLE (what to negotiate, specific changes to request) not generic advice. Maximum 45 words.'
        ),
        (
            'system',
            f'Propose replacement clauses that are: (1) specific to {doc_type_name} best practices, (2) address the exact risk identified, (3) use formal legal language, (4) provide concrete terms/numbers/timeframes where applicable. Maximum 120 words.'
        ),
        *example_messages,
        (
            'human',
            "Extracted clauses to analyze:\n{focus_text}\n\nReturn a JSON object with keys 'summary' and 'high_risk_clauses'.\n- Summary <=140 words describing the overall risk.\n- 'high_risk_clauses' is a list (0-6) of objects with 'clause_text', 'risk_score', 'risk_level', 'rationale', 'mitigation', 'replacement_clause'.\n- 'risk_score' must be an integer from 1 (minimal) to 5 (critical); align risk_level wording with the number.\n- Copy clause_text verbatim from the excerpts.\n- Keep rationale under 45 words.\n- 'mitigation' should be a concrete revision or negotiation step (<=45 words).\n- 'replacement_clause' must be formal legal language (<=120 words) that the client can propose as a safer substitute."
        ),
    ])

    try:
        chain = focus_prompt | structured_llm
        result = chain.invoke({
            'focus_text': focus_text,
        })

        if hasattr(result, 'model_dump'):
            data = result.model_dump()
        elif hasattr(result, 'dict'):
            data = result.dict()
        else:
            data = dict(result or {})

        summary_text = (data.get('summary') or '').strip()
        focus_clauses: List[Dict[str, Any]] = []

        for clause in data.get('high_risk_clauses') or []:
            if hasattr(clause, 'model_dump'):
                clause = clause.model_dump()
            elif hasattr(clause, 'dict'):
                clause = clause.dict()
            normalized = _normalize_clause_structure(clause)
            if normalized:
                focus_clauses.append(normalized)

        if not focus_clauses:
            focus_clauses = _fallback_risk_clauses(focus_text, limit=4)

        focus_result = {
            'summary': summary_text,
            'high_risk_clauses': focus_clauses,
        }

        set_cached_focus_analysis(focus_text, focus_result)
        return focus_result

    except Exception as exc:  # pylint: disable=broad-except
        error_message = str(exc)
        logger.warning("Focus snippet analysis failed, using heuristic fallback: %s", error_message)

        if (GoogleModelNotFound and isinstance(exc, GoogleModelNotFound)) or 'NotFound' in error_message:
            LLM_AVAILABLE = False
            LLM_LAST_ERROR = error_message
            logger.error(
                "Disabling Gemini LLM due to NotFound error during focus analysis. Configure settings.GEMINI_MODEL with an available model name.")

        fallback_result = {
            'summary': textwrap.shorten(focus_text.replace('\n', ' '), width=360, placeholder='…'),
            'high_risk_clauses': _fallback_risk_clauses(focus_text, limit=4),
        }
        set_cached_focus_analysis(focus_text, fallback_result)
        return fallback_result


def generate_document_analysis(text: str) -> Dict[str, Any]:
    """Run LangChain + Gemini to summarize and flag risky clauses."""
    full_text = text
    preview_excerpt = text[:2000]
    truncated_document = text[:6000]
    chunks = _chunk_document(full_text)
    keyword_sentences = _extract_keyword_sentences(full_text)

    global LLM_AVAILABLE, LLM_LAST_ERROR

    if not settings.GEMINI_API_KEY or not LLM_AVAILABLE:
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not configured; falling back to heuristic analysis.")
        elif LLM_LAST_ERROR:
            logger.warning("Gemini model disabled due to previous error: %s", LLM_LAST_ERROR)

        analysis = _generate_mock_analysis(full_text, preview_excerpt, truncated_document)
        if LLM_LAST_ERROR:
            note = "\n\nLLM Note: Gemini call disabled ({error}). Configure settings.GEMINI_MODEL with a supported model name or update API access.".format(
                error=LLM_LAST_ERROR.split('\n')[0]
            )
            analysis['summary'] = (analysis.get('summary') or '') + note
        return analysis

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.prompts import ChatPromptTemplate
        from pydantic import BaseModel, Field
    except ImportError as exc:
        logger.warning("LangChain dependencies are missing: %s", exc)
        return _generate_mock_analysis(full_text, preview_excerpt, truncated_document)

    class ClauseHighlight(BaseModel):
        clause_text: str = Field(..., description="Exact clause copied from the chunk that signals elevated risk.")
        risk_score: int = Field(..., description="Integer risk score from 1 (minimal) to 5 (critical).", ge=1, le=5)
        risk_level: str = Field(..., description="Risk severity label that aligns with the assigned risk_score.")
        rationale: str = Field(..., description="Brief explanation (<=50 words) of why the clause is risky.")
        mitigation: str = Field(..., description="Specific revision or negotiation request (<=45 words) to reduce the highlighted risk.")
        replacement_clause: str = Field(..., description="Low-risk replacement clause in formal legal language that can substitute the risky clause.")

    class DocumentAnalysis(BaseModel):
        summary: str = Field(..., description="Concise (<=140 words) synopsis of the chunk.")
        high_risk_clauses: List[ClauseHighlight] = Field(default_factory=list, description="Clauses in the chunk that warrant attention.")

    # Step 1: Classify document type for tailored analysis
    from .document_classifier import classify_document, get_type_specific_system_prompt, get_type_specific_examples, DOCUMENT_TYPES
    from .enhanced_risk_patterns import (
        get_enhanced_risk_patterns_by_type,
        generate_dynamic_alternative_clause,
        get_type_specific_mitigation_strategies
    )
    
    doc_type, confidence = classify_document(full_text, title='')
    doc_type_name = DOCUMENT_TYPES.get(doc_type, {}).get('name', 'General Agreement')
    logger.info(f"Document classified as: {doc_type_name} (confidence: {confidence:.0%})")
    
    # Get type-specific prompts
    type_specific_prompt = get_type_specific_system_prompt(doc_type)
    type_specific_examples = get_type_specific_examples(doc_type)
    
    # Get enhanced risk patterns and mitigation strategies for this document type
    risk_patterns = get_enhanced_risk_patterns_by_type(doc_type)
    mitigation_strategies = get_type_specific_mitigation_strategies(doc_type)
    
    # Build detailed pattern context for chunk analysis
    pattern_guidance = ""
    if risk_patterns:
        pattern_details = []
        for risk_category, pattern_info in risk_patterns.items():
            pattern_details.append(
                f"\n{risk_category.replace('_', ' ').title()}:\n"
                f"  Risk: {pattern_info['context']}\n"
                f"  Severity: {pattern_info['severity']}/5\n"
                f"  Solution Approach: {pattern_info['solution_template'][:150]}...\n"
                f"  Replacement Pattern: {pattern_info['alternative_pattern'][:150]}..."
            )
        if pattern_details:
            pattern_guidance = (
                f"\n\n=== ENHANCED {doc_type_name.upper()} RISK DETECTION PATTERNS ===\n" +
                "\n".join(pattern_details[:5]) +  # Show top 5 patterns
                f"\n\n=== MITIGATION STRATEGIES FOR {doc_type_name.upper()} ===\n"
                f"General: {mitigation_strategies.get('general', '')}\n"
            )
    
    # Get improved prompts and enhance with type-specific content and patterns
    improved_prompts = get_improved_system_messages()
    improved_prompts['system_prompt'] = type_specific_prompt + pattern_guidance
    
    # Build example messages from type-specific examples
    example_messages = []
    if type_specific_examples and len(type_specific_examples) > 0:
        # Use first example as the demonstration
        example = type_specific_examples[0]
        example_messages.extend([
            (
                'human',
                f"Example chunk:\n{example['clause_text']}"
            ),
            (
                'ai',
                '{{"summary": "' + example['rationale'] + '", "high_risk_clauses": ['
                '{{"clause_text": "' + example['clause_text'] + '", '
                f'"risk_score": {example["risk_score"]}, "risk_level": "{example["risk_level"]}", '
                '"rationale": "' + example['rationale'] + '", '
                '"mitigation": "' + example['mitigation'] + '", '
                '"replacement_clause": "' + example['replacement_clause'] + '"}}]}}'
            )
        ])
    else:
        # Fallback to generic example
        example_messages.extend([
            (
                'human',
                "Example chunk:\nThe Supplier shall indemnify and hold harmless the Client from any and all claims, damages, and expenses."
            ),
            (
                'ai',
                '{{"summary": "Broad indemnity shifting losses to supplier.", "high_risk_clauses": ['
                '{{"clause_text": "The Supplier shall indemnify and hold harmless the Client from any and all claims, damages, and expenses.", '
                '"risk_score": 5, "risk_level": "Critical", "rationale": "Broad indemnity obligates the supplier to cover all claims and expenses.", '
                '"mitigation": "Limit indemnity to third-party losses caused by the supplier and cap recovery to amounts paid.", '
                '"replacement_clause": "Each party shall indemnify the other solely for third-party claims arising from its own negligence or willful misconduct, subject to the liability caps set forth in this Agreement."}}]}}'
            )
        ])
    
    prompt = ChatPromptTemplate.from_messages([
        (
            'system',
            improved_prompts['system_prompt']
        ),
        (
            'system',
            'Output must be a single valid JSON object that conforms to the schema. Do not wrap the JSON in code fences, prose, or commentary.'
        ),
        (
            'system',
            improved_prompts['chunk_instructions']
        ),
        (
            'system',
            f'For each risky clause in this {doc_type_name}, provide SPECIFIC, ACTIONABLE mitigation based on industry best practices. '
            f'General guidance: {mitigation_strategies.get("general", "Negotiate balanced terms with clear limits and mutual obligations.")} '
            'Maximum 45 words per mitigation.'
        ),
        (
            'system',
            f'Draft replacement clauses that: (1) address the specific risk type identified, (2) follow {doc_type_name} best practices, '
            '(3) include concrete terms/timeframes/limits where applicable, (4) use formal legal language suitable for contract negotiation. Maximum 120 words per clause.'
        ),
        *example_messages,
        (
            'human',
            "Chunk {chunk_index} of length {chunk_length} characters:\n{chunk_text}\n\n"
            "Return a JSON object with keys 'summary' and 'high_risk_clauses'.\n"
            "- 'summary' must be <=140 words describing the chunk risk profile.\n"
            "- 'high_risk_clauses' must be a list of 0-4 objects, each containing 'clause_text', 'risk_score', 'risk_level', 'rationale', 'mitigation', and 'replacement_clause'.\n"
            "- 'risk_score' is an integer 1-5 where 5 is most severe; align risk_level wording with the numeric rating.\n"
            "\n"
            "CRITICAL FOR 'clause_text':\n"
            "  • Extract COMPLETE clauses starting at sentence/paragraph boundaries\n"
            "  • Include full sentences forming ONE coherent statement about the risk\n"
            "  • DO NOT start mid-sentence or with fragments\n"
            "  • Minimum 20-30 words for completeness\n"
            "  • Copy verbatim from this chunk\n"
            "\n"
            "- Keep rationale under 50 words.\n"
            "- 'mitigation' must be <=45 words describing a concrete revision or negotiation ask to reduce the risk.\n"
            "- 'replacement_clause' must be formal legal language (<=120 words) offering a safer substitute clause that addresses the risk.\n"
            "- If no risky language, use an empty list and note the chunk appears low risk."
        ),
    ])

    llm = ChatGoogleGenerativeAI(
        model=_get_llm_model_name(),
        temperature=0.15,
        max_output_tokens=1200,
        google_api_key=settings.GEMINI_API_KEY,
        # DO NOT set response_mime_type - conflicts with with_structured_output()
    )

    structured_llm = llm.with_structured_output(DocumentAnalysis)

import concurrent.futures # New import

# ... (rest of the imports)

def generate_document_analysis(text: str) -> Dict[str, Any]:
    """Run LangChain + Gemini to summarize and flag risky clauses."""
    full_text = text
    preview_excerpt = text[:2000]
    truncated_document = text[:6000]
    chunks = _chunk_document(full_text)
    keyword_sentences = _extract_keyword_sentences(full_text)

    global LLM_AVAILABLE, LLM_LAST_ERROR

    if not settings.GEMINI_API_KEY or not LLM_AVAILABLE:
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not configured; falling back to heuristic analysis.")
        elif LLM_LAST_ERROR:
            logger.warning("Gemini model disabled due to previous error: %s", LLM_LAST_ERROR)

        analysis = _generate_mock_analysis(full_text, preview_excerpt, truncated_document)
        if LLM_LAST_ERROR:
            note = "\n\nLLM Note: Gemini call disabled ({error}). Configure settings.GEMINI_MODEL with a supported model name or update API access.".format(
                error=LLM_LAST_ERROR.split('\n')[0]
            )
            analysis['summary'] = (analysis.get('summary') or '') + note
        return analysis

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.prompts import ChatPromptTemplate
        from pydantic import BaseModel, Field
    except ImportError as exc:
        logger.warning("LangChain dependencies are missing: %s", exc)
        return _generate_mock_analysis(full_text, preview_excerpt, truncated_document)

    class ClauseHighlight(BaseModel):
        clause_text: str = Field(..., description="Exact clause copied from the chunk that signals elevated risk.")
        risk_score: int = Field(..., description="Integer risk score from 1 (minimal) to 5 (critical).", ge=1, le=5)
        risk_level: str = Field(..., description="Risk severity label that aligns with the assigned risk_score.")
        rationale: str = Field(..., description="Brief explanation (<=50 words) of why the clause is risky.")
        mitigation: str = Field(..., description="Specific revision or negotiation request (<=45 words) to reduce the highlighted risk.")
        replacement_clause: str = Field(..., description="Low-risk replacement clause in formal legal language that can substitute the risky clause.")

    class DocumentAnalysis(BaseModel):
        summary: str = Field(..., description="Concise (<=140 words) synopsis of the chunk.")
        high_risk_clauses: List[ClauseHighlight] = Field(default_factory=list, description="Clauses in the chunk that warrant attention.")

    # Step 1: Classify document type for tailored analysis
    from .document_classifier import classify_document, get_type_specific_system_prompt, get_type_specific_examples, DOCUMENT_TYPES
    from .enhanced_risk_patterns import (
        get_enhanced_risk_patterns_by_type,
        generate_dynamic_alternative_clause,
        get_type_specific_mitigation_strategies
    )
    
    doc_type, confidence = classify_document(full_text, title='')
    doc_type_name = DOCUMENT_TYPES.get(doc_type, {}).get('name', 'General Agreement')
    logger.info(f"Document classified as: {doc_type_name} (confidence: {confidence:.0%})")
    
    # Get type-specific prompts
    type_specific_prompt = get_type_specific_system_prompt(doc_type)
    type_specific_examples = get_type_specific_examples(doc_type)
    
    # Get enhanced risk patterns and mitigation strategies for this document type
    risk_patterns = get_enhanced_risk_patterns_by_type(doc_type)
    mitigation_strategies = get_type_specific_mitigation_strategies(doc_type)
    
    # Build detailed pattern context for chunk analysis
    pattern_guidance = ""
    if risk_patterns:
        pattern_details = []
        for risk_category, pattern_info in risk_patterns.items():
            pattern_details.append(
                f"\n{risk_category.replace('_', ' ').title()}:\n"
                f"  Risk: {pattern_info['context']}\n"
                f"  Severity: {pattern_info['severity']}/5\n"
                f"  Solution Approach: {pattern_info['solution_template'][:150]}...\n"
                f"  Replacement Pattern: {pattern_info['alternative_pattern'][:150]}..."
            )
        if pattern_details:
            pattern_guidance = (
                f"\n\n=== ENHANCED {doc_type_name.upper()} RISK DETECTION PATTERNS ===\n" +
                "\n".join(pattern_details[:5]) +  # Show top 5 patterns
                f"\n\n=== MITIGATION STRATEGIES FOR {doc_type_name.upper()} ===\n"
                f"General: {mitigation_strategies.get('general', '')}\n"
            )
    
    # Get improved prompts and enhance with type-specific content and patterns
    improved_prompts = get_improved_system_messages()
    improved_prompts['system_prompt'] = type_specific_prompt + pattern_guidance
    
    # Build example messages from type-specific examples
    example_messages = []
    if type_specific_examples and len(type_specific_examples) > 0:
        # Use first example as the demonstration
        example = type_specific_examples[0]
        example_messages.extend([
            (
                'human',
                f"Example chunk:\n{example['clause_text']}"
            ),
            (
                'ai',
                '{{"summary": "' + example['rationale'] + '", "high_risk_clauses": ['
                '{{"clause_text": "' + example['clause_text'] + '", '
                f'"risk_score": {example["risk_score"]}, "risk_level": "{example["risk_level"]}", '
                '"rationale": "' + example['rationale'] + '", '
                '"mitigation": "' + example['mitigation'] + '", '
                '"replacement_clause": "' + example['replacement_clause'] + '"}}]}}'
            )
        ])
    else:
        # Fallback to generic example
        example_messages.extend([
            (
                'human',
                "Example chunk:\nThe Supplier shall indemnify and hold harmless the Client from any and all claims, damages, and expenses."
            ),
            (
                'ai',
                '{{"summary": "Broad indemnity shifting losses to supplier.", "high_risk_clauses": ['
                '{{"clause_text": "The Supplier shall indemnify and hold harmless the Client from any and all claims, damages, and expenses.", '
                '"risk_score": 5, "risk_level": "Critical", "rationale": "Broad indemnity obligates the supplier to cover all claims and expenses.", '
                '"mitigation": "Limit indemnity to third-party losses caused by the supplier and cap recovery to amounts paid.", '
                '"replacement_clause": "Each party shall indemnify the other solely for third-party claims arising from its own negligence or willful misconduct, subject to the liability caps set forth in this Agreement."}}]}}'
            )
        ])
    
    prompt = ChatPromptTemplate.from_messages([
        (
            'system',
            improved_prompts['system_prompt']
        ),
        (
            'system',
            'Output must be a single valid JSON object that conforms to the schema. Do not wrap the JSON in code fences, prose, or commentary.'
        ),
        (
            'system',
            improved_prompts['chunk_instructions']
        ),
        (
            'system',
            f'For each risky clause in this {doc_type_name}, provide SPECIFIC, ACTIONABLE mitigation based on industry best practices. '
            f'General guidance: {mitigation_strategies.get("general", "Negotiate balanced terms with clear limits and mutual obligations.")} '
            'Maximum 45 words per mitigation.'
        ),
        (
            'system',
            f'Draft replacement clauses that: (1) address the specific risk type identified, (2) follow {doc_type_name} best practices, '
            '(3) include concrete terms/timeframes/limits where applicable, (4) use formal legal language suitable for contract negotiation. Maximum 120 words per clause.'
        ),
        *example_messages,
        (
            'human',
            "Chunk {chunk_index} of length {chunk_length} characters:\n{chunk_text}\n\n"
            "Return a JSON object with keys 'summary' and 'high_risk_clauses'.\n"
            "- 'summary' must be <=140 words describing the chunk risk profile.\n"
            "- 'high_risk_clauses' must be a list of 0-4 objects, each containing 'clause_text', 'risk_score', 'risk_level', 'rationale', 'mitigation', and 'replacement_clause'.\n"
            "- 'risk_score' is an integer 1-5 where 5 is most severe; align risk_level wording with the numeric rating.\n"
            "\n"
            "CRITICAL FOR 'clause_text':\n"
            "  • Extract COMPLETE clauses starting at sentence/paragraph boundaries\n"
            "  • Include full sentences forming ONE coherent statement about the risk\n"
            "  • DO NOT start mid-sentence or with fragments\n"
            "  • Minimum 20-30 words for completeness\n"
            "  • Copy verbatim from this chunk\n"
            "\n"
            "- Keep rationale under 50 words.\n"
            "- 'mitigation' must be <=45 words describing a concrete revision or negotiation ask to reduce the risk.\n"
            "- 'replacement_clause' must be formal legal language (<=120 words) offering a safer substitute clause that addresses the risk.\n"
            "- If no risky language, use an empty list and note the chunk appears low risk."
        ),
    ])

    llm = ChatGoogleGenerativeAI(
        model=_get_llm_model_name(),
        temperature=0.15,
        max_output_tokens=1200,
        google_api_key=settings.GEMINI_API_KEY,
        # DO NOT set response_mime_type - conflicts with with_structured_output()
    )

    structured_llm = llm.with_structured_output(DocumentAnalysis)

    summary_parts: List[str] = []
    clause_candidates: List[Dict[str, Any]] = []
    chunk_results: List[Dict[str, Any]] = [None] * len(chunks) # Pre-allocate for ordered results

    if not chunks:
        chunks = [{'text': full_text, 'start': 0, 'end': len(full_text)}]

    keyword_scores = [(_keyword_score(chunk['text']), idx) for idx, chunk in enumerate(chunks)]
    keyword_scores.sort(reverse=True)

    max_llm_chunks = min(6, len(chunks))
    llm_indices = {idx for score, idx in keyword_scores if score > 0}
    llm_indices = set(list(llm_indices)[:max_llm_chunks])

    if not llm_indices and chunks:
        llm_indices = {0}

    # Max workers for ThreadPoolExecutor. Adjust based on available resources and API rate limits.
    # A common heuristic for I/O bound tasks is (2 * num_cores) + 1.
    # Given Gemini API calls are primary I/O, a higher number might be fine but needs testing.
    # Let's start with 4 workers to avoid overwhelming the API or local resources.
    # We should also consider settings.CELERY_WORKER_COUNT or a similar config if available.
    num_workers = min(len(chunks), 4) # Don't use more workers than chunks

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {}
        for idx, chunk in enumerate(chunks):
            if idx in llm_indices:
                future = executor.submit(
                    _analyze_chunk_with_llm,
                    chunk=chunk,
                    idx=idx,
                    prompt=prompt,
                    structured_llm=structured_llm,
                )
            else:
                # For non-LLM chunks, just run the fallback directly (it's fast and doesn't need a separate thread)
                # Or submit a simple lambda for consistency in result collection
                future = executor.submit(
                    lambda c, i: {
                        'summary': textwrap.shorten(c['text'].replace('\n', ' '), width=260, placeholder='…'),
                        'high_risk_clauses': _fallback_risk_clauses(c['text'], limit=2),
                    },
                    chunk,
                    idx
                )
            futures[future] = idx # Map future back to original index

        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            try:
                chunk_result = future.result()
                chunk_results[idx] = chunk_result
            except Exception as exc:
                logger.error(f"Error processing chunk {idx} in parallel: {exc}", exc_info=True)
                # Fallback for failed LLM chunk if any
                chunk_results[idx] = {
                    'summary': textwrap.shorten(chunks[idx]['text'].replace('\n', ' '), width=260, placeholder='…'),
                    'high_risk_clauses': _fallback_risk_clauses(chunks[idx]['text'], limit=2),
                }

    # After parallel execution, process ordered_chunk_results
    for chunk_result in chunk_results:
        if chunk_result: # Ensure it's not None
            if chunk_result.get('summary'):
                summary_parts.append(chunk_result['summary'])
            clause_candidates.extend(chunk_result.get('high_risk_clauses') or [])
    
    # ... (rest of the generate_document_analysis function)

    if keyword_sentences and len(clause_candidates) < 6:
        focus_result = _analyze_focus_snippets(
            snippets=keyword_sentences[:12],
            structured_llm=structured_llm,
            doc_type=doc_type,
        )
        if focus_result.get('summary'):
            summary_parts.append(focus_result['summary'])
        clause_candidates.extend(focus_result.get('high_risk_clauses') or [])

    # Always run enhanced heuristic detection as a safety net
    heuristic_risks = detect_enhanced_risks(full_text, max_clauses=10)
    
    if not clause_candidates:
        # Convert heuristic risks to expected format
        clause_candidates = []
        for risk in heuristic_risks:
            category = risk.get('category', 'generic')
            clause_candidates.append({
                'clause_text': risk['clause_text'],
                'risk_level': risk['risk_level'],
                'risk_score': risk['risk_score'],
                'rationale': risk['rationale'],
                'mitigation': risk['mitigation'],
                'replacement_clause': DEFAULT_REPLACEMENTS.get(category, DEFAULT_REPLACEMENTS['generic']),
                'confidence': risk.get('confidence', 0.75),
                'source': 'heuristic'
            })
        if clause_candidates:
            summary_parts.append("Enhanced pattern matching detected high-risk clauses.")
    else:
        # Merge LLM and heuristic results intelligently
        clause_candidates = merge_llm_and_heuristic_risks(
            llm_clauses=clause_candidates,
            heuristic_clauses=[
                {
                    'clause_text': risk['clause_text'],
                    'risk_level': risk['risk_level'],
                    'risk_score': risk['risk_score'],
                    'rationale': risk['rationale'],
                    'mitigation': risk['mitigation'],
                    'replacement_clause': DEFAULT_REPLACEMENTS.get(
                        risk.get('category', 'generic'),
                        DEFAULT_REPLACEMENTS['generic']
                    ),
                    'confidence': risk.get('confidence', 0.75),
                    'weight': risk.get('weight', 5.0)
                }
                for risk in heuristic_risks
            ],
            max_total=10
        )

    deduped_clauses = _dedupe_clauses(clause_candidates, limit=8)
    deduped_clauses = _order_clauses_by_priority(deduped_clauses, full_text)

    # TWO-STAGE REFINEMENT: Use pattern templates + Gemini to tailor solutions
    # Stage 1: Gemini identified risks (already done above)
    # Stage 2: Match patterns -> Get templates -> Gemini tailors to specific clause
    if SOLUTION_REFINEMENT_AVAILABLE and deduped_clauses:
        logger.info(f"Refining {len(deduped_clauses)} clauses with pattern-based templates + Gemini tailoring")
        try:
            deduped_clauses = batch_refine_clauses(
                clauses=deduped_clauses,
                doc_type=doc_type,
                structured_llm=llm,  # Pass base LLM, refinement will bind to RefinedSolution schema
                full_text=full_text,
                max_refine=6,  # Refine top 6 highest-risk clauses
            )
            logger.info("Solution refinement completed successfully")
        except Exception as exc:
            logger.warning(f"Solution refinement failed, using original solutions: {exc}")
    else:
        if not SOLUTION_REFINEMENT_AVAILABLE:
            logger.warning("Solution refinement not available, using original solutions")

    # Build highlighted preview with full clause text and track which clauses were highlighted
    highlighted_preview, highlighted_indices, expanded_clause_texts = _build_highlighted_preview(full_text, deduped_clauses)
    
    # Prepare clauses for response - only include successfully highlighted clauses
    response_clauses = []
    for clause_idx, clause in enumerate(deduped_clauses):
        # Only include clauses that were successfully highlighted
        if clause_idx not in highlighted_indices:
            clause_text = clause.get('clause_text', '')
            logger.info(f"Excluding clause (not highlighted): {clause_text[:60]}...")
            continue
        response_clause = clause.copy()
        
        # Use the expanded sentence boundary text for display synchronization
        expanded_text = expanded_clause_texts.get(clause_idx)
        if expanded_text:
            response_clause['clause_text'] = expanded_text
            clause_text = expanded_text
            logger.info(f"Using expanded clause text ({len(expanded_text)} chars): {expanded_text[:60]}...")
        else:
            clause_text = clause.get('clause_text', '')
        
        # Get refined solutions from clause (updated by refinement process)
        replacement = clause.get('replacement_clause', '')
        risk_score = clause.get('risk_score', 3)
        mitigation = clause.get('mitigation', '')
        
        # Log refinement status
        refinement_method = clause.get('refinement_method')
        if refinement_method:
            logger.info(f"Clause {clause_idx} refined using: {refinement_method}")
            logger.info(f"  Mitigation length: {len(mitigation)} chars")
            logger.info(f"  Replacement length: {len(replacement)} chars")
            if mitigation:
                logger.info(f"  Mitigation preview: {mitigation[:80]}...")
            if replacement:
                logger.info(f"  Replacement preview: {replacement[:80]}...")
        
        # IMPORTANT: Minimal filtering only - clause was already validated by successful highlighting
        # If it's highlighted in preview, it should appear in the clause section
        
        # Only filter extremely low risk scores that shouldn't have been highlighted
        if risk_score <= 1:
            logger.info(f"Filtering minimal risk clause (score {risk_score}): {clause_text[:60]}...")
            continue
        
        # Keep pattern metadata if present (from refinement process)
        if clause.get('pattern_matched'):
            response_clause['pattern_matched'] = clause['pattern_matched']
        if clause.get('pattern_severity'):
            response_clause['pattern_severity'] = clause['pattern_severity']
        if clause.get('refinement_method'):
            response_clause['refinement_method'] = clause['refinement_method']
        
        # If clause is very long, provide shortened version for display
        if len(clause_text) > 500:
            # Try to end at a sentence boundary
            short_text = clause_text[:500]
            last_period = short_text.rfind('.')
            last_question = short_text.rfind('?')
            last_exclaim = short_text.rfind('!')
            sentence_end = max(last_period, last_question, last_exclaim)
            
            if sentence_end > 400:  # If we found a reasonable sentence boundary
                response_clause['clause_text'] = clause_text[:sentence_end + 1]
                response_clause['clause_text_truncated'] = True
            else:
                response_clause['clause_text'] = clause_text[:500] + '...'
                response_clause['clause_text_truncated'] = True
        
        response_clauses.append(response_clause)

    # Generate comprehensive structured summary with configurable LLM/regex approach
    logger.info("=" * 80)
    logger.info("STARTING COMPREHENSIVE SUMMARY GENERATION")
    logger.info(f"Input data: doc_type={doc_type}, doc_type_name={doc_type_name}, chunk_results={len(chunk_results)}, deduped_clauses={len(deduped_clauses)}")
    logger.info(f"Full text length: {len(full_text)} chars")
    logger.info(f"LLM available: {LLM_AVAILABLE}")
    
    comprehensive_summary = None
    
    # Configurable: Try LLM first if available, with automatic fallback to regex on quota issues
    use_llm_for_summary = LLM_AVAILABLE and settings.GEMINI_API_KEY
    
    if use_llm_for_summary:
        logger.info("Attempting LLM-based comprehensive summary generation (will fallback to regex if quota exceeded)...")
        try:
            comprehensive_summary = _generate_comprehensive_summary(
                full_text=full_text,
                doc_type=doc_type,
                llm=llm,
                doc_type_name=doc_type_name,
                use_llm=True
            )
            if comprehensive_summary:
                logger.info(f"✅ LLM-based comprehensive summary generated successfully")
                logger.info(f"Summary keys: {list(comprehensive_summary.keys())}")
                logger.info(f"Parties extracted: {len(comprehensive_summary.get('parties', []))}")
                logger.info(f"Financial terms: {len(comprehensive_summary.get('financial_terms', []))}")
                logger.info(f"Legal terms explained: {len(comprehensive_summary.get('legal_terms_explained', []))}")
        except Exception as exc:
            error_msg = str(exc)
            is_quota = any(indicator in error_msg.lower() for indicator in 
                          ['quota', 'rate limit', '429', 'resource exhausted'])
            if is_quota:
                logger.warning(f"LLM quota exceeded, automatically falling back to regex extraction")
            else:
                logger.warning(f"LLM-based comprehensive summary failed: {exc}")
            comprehensive_summary = None  # Will use regex fallback below
    else:
        logger.info("LLM not available, using regex-based extraction directly")
    
    # Use regex-based extraction if LLM was skipped or failed
    if not comprehensive_summary:
        logger.info("Using regex-based comprehensive summary extraction...")
        try:
            comprehensive_summary = _generate_comprehensive_summary_from_analysis(
                full_text=full_text,
                doc_type=doc_type,
                doc_type_name=doc_type_name,
                chunk_results=chunk_results,
                deduped_clauses=deduped_clauses
            )
            if comprehensive_summary:
                logger.info(f"✅ Regex-based comprehensive summary generated")
                logger.info(f"Parties extracted: {len(comprehensive_summary.get('parties', []))}")
                logger.info(f"Financial terms: {len(comprehensive_summary.get('financial_terms', []))}")
        except Exception as exc:
            logger.error(f"❌ Regex extraction also failed: {exc}", exc_info=True)
    
    # Final fallback: Create minimal comprehensive summary if both methods failed
    if not comprehensive_summary:
        logger.warning("Creating minimal fallback comprehensive summary")
        comprehensive_summary = {
            'document_type': doc_type_name,
            'execution_date': None,
            'parties': [],
            'purpose': f"This is a {doc_type_name}.",
            'key_obligations': {},
            'financial_terms': [],
            'term_and_termination': {
                'duration': 'Not specified',
                'termination_process': 'Not specified',
                'simple_explanation': 'Review document for term details'
            },
            'compliance_requirements': [],
            'important_deadlines': [],
            'attachments_mentioned': [],
            'legal_terms_explained': [],
            'executive_summary': summary_parts[0] if summary_parts else 'Document analysis completed.',
        }
        logger.info("✅ Fallback comprehensive summary created")
    
    logger.info("=" * 80)
    
    # Also keep the quick summary from chunk analysis for backwards compatibility
    summary_text = _merge_summaries(summary_parts)
    if not summary_text and comprehensive_summary:
        summary_text = comprehensive_summary.get('executive_summary', '')
    
    if not summary_text:
        summary_text = textwrap.shorten(
            truncated_document.replace('\n', ' '),
            width=500,
            placeholder='…'
        ) if truncated_document else ''

    response_data = {
        'summary': summary_text,
        'comprehensive_summary': comprehensive_summary,  # Always include, even if it's fallback
        'high_risk_clauses': response_clauses,
        'highlighted_preview': highlighted_preview,
        'preview_text': full_text,
        'document_type': doc_type_name,
        'document_type_confidence': round(confidence * 100, 1),
        'source': 'chunked-gemini',
    }
    
    logger.info(f"✅ Response data prepared with comprehensive_summary: {comprehensive_summary is not None}")
    logger.info(f"Final response_data keys: {list(response_data.keys())}")
    
    return response_data

def extract_text_from_file(uploaded_file):
    """Extract text depending on file type."""
    if uploaded_file.name.endswith('.pdf'):
        try:
            text = ""
            with fitz.open(stream=uploaded_file.read(), filetype="pdf") as doc:
                for page in doc:
                    text += page.get_text()
            return text
        except fitz.FileDataError as e:
            return None
        except Exception as e:
            raise Exception(f"Error extracting text from PDF: {str(e)}")

    elif uploaded_file.name.endswith('.docx'):
        doc = Document(uploaded_file)
        return "\n".join([p.text for p in doc.paragraphs])

    elif uploaded_file.name.endswith('.txt'):
        return uploaded_file.read().decode('utf-8')

    else:
        return None

def chat_with_document(session, user_message):
    """Use Gemini API to answer questions about the document."""
    try:
        genai_client = get_gemini_client()
        model = genai_client.GenerativeModel(_get_llm_model_name())
        
        # Get chat history for context
        recent_messages = ChatMessage.objects(session=session).order_by('created_at')[:10]

        risk_lines = []
        for clause in (session.high_risk_clauses or [])[:5]:
            clause_text = (clause.get('clause_text') or '').replace('\n', ' ').strip()
            rationale = (clause.get('rationale') or '').replace('\n', ' ').strip()
            risk_score = _coerce_risk_score(clause.get('risk_score') or clause.get('riskScore'), default=3)
            risk_level = clause.get('risk_level') or clause.get('riskLevel') or _score_to_label(risk_score)
            mitigation = (clause.get('mitigation') or clause.get('recommendation') or clause.get('suggestion') or '').replace('\n', ' ').strip()
            replacement = (clause.get('replacement_clause') or clause.get('replacementClause') or clause.get('alternate_clause') or '').replace('\n', ' ').strip()
            if clause_text:
                details = f"- Risk score: {risk_score}/5 ({risk_level}). Clause: {clause_text[:220]}"
                if rationale:
                    details += f". Rationale: {rationale[:180]}"
                if mitigation:
                    details += f". Suggested mitigation: {mitigation[:180]}"
                if replacement:
                    details += f". Alternate clause: {replacement[:220]}"
                risk_lines.append(details)

        risk_overview = '\n'.join(risk_lines) if risk_lines else 'No high risk clauses were highlighted in the initial analysis.'

        preview_for_prompt = session.highlighted_preview or ''
        if preview_for_prompt:
            preview_for_prompt = html.unescape(preview_for_prompt)
            preview_for_prompt = preview_for_prompt.replace('<mark class="high-risk">', '[HIGH-RISK]').replace('</mark>', '[/HIGH-RISK]')
            preview_for_prompt = preview_for_prompt.replace('<br />', '\n').replace('<br/>', '\n')
        else:
            preview_for_prompt = session.document_text[:1500]
        
        messages = [
            {"role": "user", "parts": [f"""You are a legal assistant helping a user understand a legal document.
Original Document (first 5000 characters):
{session.document_text[:5000]}
Document Summary:
{session.summary}
High Risk Clauses Overview:
{risk_overview}
Highlighted Preview (HIGH-RISK marks indicate clauses the analysis flagged):
{preview_for_prompt}
Please provide a helpful, accurate response based on the document content and summary.
If the question cannot be answered from the document, politely state that.
Keep your response clear and concise.
"""]},
            {"role": "model", "parts": ["Okay, I am ready to help you with your document."]}
        ]
        
        for msg in recent_messages:
            role = 'user' if msg.is_user else 'model' # Gemini uses 'model' for assistant
            messages.append({"role": role, "parts": [msg.message]})
            
        messages.append({"role": "user", "parts": [user_message]})

        chat_completion = model.generate_content(
            messages,
            generation_config=genai_client.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=500, # Limit response length
            ),
            request_options={'timeout': 60} # Increase timeout to 60 seconds
        )
        return chat_completion.candidates[0].content.parts[0].text
    except Exception as e:
        raise Exception(f"Error generating response with Gemini API: {str(e)}")

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def summarize_document(request):
    """API endpoint for document summarization with async processing support"""
    try:
        # Check if async mode is requested
        async_value = request.data.get('async', 'false')
        async_mode = str(async_value).lower() == 'true' if async_value else False
        
        uploaded_file = request.FILES.get('document')
        if not uploaded_file:
            return Response({
                'error': 'Please upload a document'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Check file size (limit to 10MB)
        if uploaded_file.size > 10 * 1024 * 1024:
            return Response({
                'error': 'File size exceeds 10MB limit.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Reset file pointer to beginning for reading content
        uploaded_file.seek(0)

        try:
            text = extract_text_from_file(uploaded_file)
            if text is None:
                return Response({
                    'error': 'Error extracting text from file.'
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'error': f'Error extracting text from file: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        if not text:
            return Response({
                'error': 'Unsupported file type. Please upload PDF, DOCX, or TXT'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Get user from JWT token
        user = request.user
        
        if not user:
            return Response({
                'error': 'User not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Create session first
        session = DocumentSession(
            user=user,
            document_text=text,
            summary='Processing...',  # Placeholder
            highlighted_preview='',
            high_risk_clauses=[],
        )
        session.save()
        
        # If async mode, queue the task and return immediately
        if async_mode:
            from .tasks import analyze_document_async
            
            # Set initial task status
            set_task_status(str(session.id), 'pending', 0, 'Queued for analysis')
            
            # Queue the async task
            analyze_document_async.delay(str(session.id), text)
            
            return Response({
                'success': True,
                'async': True,
                'session_id': str(session.id),
                'filename': uploaded_file.name,
                'status': 'pending',
                'message': 'Document queued for analysis. Check status endpoint for progress.'
            }, status=status.HTTP_202_ACCEPTED)
        
        # Synchronous processing (original behavior)
        analysis = generate_document_analysis(text)
        # Update session with analysis results
        session.summary = analysis.get('summary') or textwrap.shorten(
            text.replace('\n', ' '),
            width=500,
            placeholder='…'
        )
        session.highlighted_preview = analysis.get('highlighted_preview') or html.escape(text).replace('\n', '<br />')
        session.high_risk_clauses = analysis.get('high_risk_clauses') or []
        session.comprehensive_summary = analysis.get('comprehensive_summary')
        session.document_type = analysis.get('document_type')
        session.document_type_confidence = analysis.get('document_type_confidence')
        session.save()
        
        preview_text = analysis.get('preview_text') or text
        
        return Response({
            'success': True,
            'async': False,
            'summary': session.summary,
            'comprehensive_summary': analysis.get('comprehensive_summary'),  # ADD THIS
            'highlighted_preview': session.highlighted_preview,
            'high_risk_clauses': session.high_risk_clauses,
            'preview_text': preview_text,
            'document_text': text,
            'document_type': analysis.get('document_type'),  # ADD THIS TOO
            'document_type_confidence': analysis.get('document_type_confidence'),  # AND THIS
            'session_id': str(session.id),
            'filename': uploaded_file.name
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from django.views.decorators.csrf import csrf_exempt # Added csrf_exempt import

# ...

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_message(request):
    """Handle chat messages"""
    try:
        user_message = request.data.get('message')
        session_id = request.data.get('session_id')
        
        if not user_message or not session_id:
            return Response({
                'error': 'Missing message or session_id'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get user from JWT token (request.user is already a User object)
        user = request.user
        
        if not user:
            return Response({
                'error': 'User not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get the document session and verify ownership
        try:
            session = DocumentSession.objects(id=session_id).first()
            if not session:
                return Response({
                    'error': 'Session not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
            if str(session.user.id) != str(user.id):
                return Response({
                    'error': 'Access denied'
                }, status=status.HTTP_403_FORBIDDEN)
        except DoesNotExist:
            return Response({
                'error': 'Session not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Save user message
        user_msg = ChatMessage(
            session=session,
            message=user_message,
            is_user=True
        )
        user_msg.save()
        
        # Get AI response
        ai_response = chat_with_document(session, user_message)
        
        # Save AI response
        ai_msg = ChatMessage(
            session=session,
            message=ai_response,
            is_user=False
        )
        ai_msg.save()
        
        return Response({
            'response': ai_response,
            'message_id': str(ai_msg.id)
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def chat_history(request, session_id):
    """Get chat history for a session"""
    try:
        # Get user from JWT token (request.user is already a User object)
        user = request.user
        
        if not user:
            return Response({
                'error': 'User not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        try:
            session = DocumentSession.objects(id=session_id).first()
            if not session:
                return Response({
                    'error': 'Session not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
            if str(session.user.id) != str(user.id):
                return Response({
                    'error': 'Access denied'
                }, status=status.HTTP_403_FORBIDDEN)
        except DoesNotExist:
            return Response({
                'error': 'Session not found'
            }, status=status.HTTP_404_NOT_FOUND)
            
        messages = ChatMessage.objects(session=session).order_by('created_at')
        
        messages_data = [
            {
                'id': str(msg.id),
                'message': msg.message,
                'is_user': msg.is_user,
                'timestamp': msg.created_at.isoformat()
            }
            for msg in messages
        ]
        
        return Response({
            'messages': messages_data,
            'session': {
                'id': str(session.id),
                'summary': session.summary,
                'highlighted_preview': session.highlighted_preview or '',
                'high_risk_clauses': session.high_risk_clauses or [],
                'preview_text': session.document_text,
                'comprehensive_summary': session.comprehensive_summary or None,
                'document_type': session.document_type or None,
                'document_type_confidence': session.document_type_confidence or None,
                'created_at': session.created_at.isoformat()
            }
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_sessions(request):
    """Get user's document sessions"""
    try:
        user = request.user
        
        if not user:
            logger.error("User not found in request")
            return Response({
                'error': 'User not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        logger.info(f"Fetching sessions for user: {user.email if hasattr(user, 'email') else user}")
        
        try:
            # Query sessions for this user
            sessions = list(DocumentSession.objects(user=user).order_by('-created_at'))
            logger.info(f"Found {len(sessions)} sessions for user {user.email if hasattr(user, 'email') else user}")
        except Exception as query_error:
            logger.error(f"Error querying DocumentSession: {str(query_error)}")
            return Response({
                'error': f'Database query failed: {str(query_error)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        if not sessions:
            # No sessions found, return empty list
            return Response({
                'sessions': []
            }, status=status.HTTP_200_OK)
        
        session_ids = [session.id for session in sessions]
        
        try:
            # Aggregate message counts for all sessions in a single query
            message_counts = list(ChatMessage._collection.aggregate([
                {'$match': {'session': {'$in': session_ids}}},
                {'$group': {'_id': '$session', 'count': {'$sum': 1}}}
            ]))
            
            # Convert list of dicts to a dict for easy lookup
            message_counts_map = {item['_id']: item['count'] for item in message_counts}
        except Exception as agg_error:
            logger.error(f"Error aggregating message counts: { str(agg_error)}")
            # Continue without message counts
            message_counts_map = {}
        
        sessions_data = []
        for session in sessions:
            try:
                message_count = message_counts_map.get(session.id, 0)
                sessions_data.append({
                    'id': str(session.id),
                    'summary_preview': (session.summary[:150] + '...' if len(session.summary) > 150 else session.summary) if session.summary else '',
                    'created_at': session.created_at.isoformat() if session.created_at else None,
                    'message_count': message_count,
                    'document_preview': (session.document_text[:100] + '...' if len(session.document_text) > 100 else session.document_text) if session.document_text else '',
                    'highlighted_preview': session.highlighted_preview or '',
                    'high_risk_clause_count': len(session.high_risk_clauses or []),
                    'comprehensive_summary': session.comprehensive_summary or None,
                    'document_type': session.document_type or None,
                    'document_type_confidence': session.document_type_confidence or None,
                })
            except Exception as session_error:
                logger.error(f"Error processing session {session.id}: {str(session_error)}")
                # Skip this session and continue
                continue
        
        logger.info(f"Successfully prepared {len(sessions_data)} sessions data")
        return Response({
            'sessions': sessions_data
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Unexpected error in user_sessions: {str(e)}", exc_info=True)
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def task_status(request, session_id):
    """Get the status of an async document analysis task"""
    try:
        user = request.user
        
        if not user:
            return Response({
                'error': 'User not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Verify session ownership
        try:
            session = DocumentSession.objects(id=session_id).first()
            if not session:
                return Response({
                    'error': 'Session not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
            if str(session.user.id) != str(user.id):
                return Response({
                    'error': 'Access denied'
                }, status=status.HTTP_403_FORBIDDEN)
        except DoesNotExist:
            return Response({
                'error': 'Session not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get task status from cache
        status_info = get_task_status(session_id)
        
        if not status_info:
            # No status in cache - check if session has results
            if session.summary and session.summary != 'Processing...':
                status_info = {
                    'status': 'completed',
                    'progress': 100,
                    'message': 'Analysis complete'
                }
            else:
                status_info = {
                    'status': 'unknown',
                    'progress': 0,
                    'message': 'No status information available'
                }
        
        # If completed, include results
        response_data = {
            'session_id': str(session.id),
            **status_info
        }
        
        if status_info['status'] == 'completed':
            response_data.update({
                'summary': session.summary,
                'highlighted_preview': session.highlighted_preview or '',
                'high_risk_clauses': session.high_risk_clauses or [],
                'high_risk_clause_count': len(session.high_risk_clauses or [])
            })
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def session_detail(request, session_id):
    """View a specific session with chat"""
    try:
        # Get user from JWT token (request.user is already a User object)
        user = request.user
        
        if not user:
            return Response({
                'error': 'User not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        try:
            session = DocumentSession.objects(id=session_id).first()
            if not session:
                return Response({
                    'error': 'Session not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
            if str(session.user.id) != str(user.id):
                return Response({
                    'error': 'Access denied'
                }, status=status.HTTP_403_FORBIDDEN)
        except DoesNotExist:
            return Response({
                'error': 'Session not found'
            }, status=status.HTTP_404_NOT_FOUND)
            
        chat_messages = ChatMessage.objects(session=session).order_by('created_at')
        
        messages_data = [
            {
                'id': str(msg.id),
                'message': msg.message,
                'is_user': msg.is_user,
                'timestamp': msg.created_at.isoformat()
            }
            for msg in chat_messages
        ]
        
        return Response({
            'session': {
                'id': str(session.id),
                'summary': session.summary,
                'highlighted_preview': session.highlighted_preview or '',
                'high_risk_clauses': session.high_risk_clauses or [],
                'preview_text': session.document_text,
                'document_text': session.document_text,
                'created_at': session.created_at.isoformat()
            },
            'messages': messages_data
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
