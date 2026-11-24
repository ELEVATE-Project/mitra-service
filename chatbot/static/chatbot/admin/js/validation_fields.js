(function(){
  "use strict";
  if(window._smValidationReady) return;
  window._smValidationReady = true;

  // ── Utility: monotonic index counter per container ──
  function getNextIndex(container){
    var nextIndex = parseInt(container.getAttribute('data-next-idx') || '0', 10);
    // Ensure we're above any existing indices
    container.querySelectorAll('.dyn-row input[name]').forEach(function(inputElement){
      var match = inputElement.name.match(/_(\d+)$/);
      if(match) nextIndex = Math.max(nextIndex, parseInt(match[1], 10) + 1);
    });
    container.setAttribute('data-next-idx', String(nextIndex + 1));
    return nextIndex;
  }

  function findFieldRows(container, fieldNames){
    var matchingRows = [];
    container.querySelectorAll('.form-group').forEach(function(formGroup){
      for(var fieldIndex = 0; fieldIndex < fieldNames.length; fieldIndex++){
        if(formGroup.classList.contains('field-' + fieldNames[fieldIndex])){
          matchingRows.push(formGroup);
          break;
        }
      }
    });
    return matchingRows;
  }

  function getContainerAndPrefix(button, type){
    var container = button.previousElementSibling;
    if (!container || !container.classList.contains('dyn-rows-container')) {
      if (button.parentElement) {
        container = button.parentElement.querySelector('.dyn-rows-container');
      }
    }
    if (!container) {
      container = document.getElementById(button.getAttribute('data-container'));
    }
    if (!container) return { container: null, prefix: '' };

    var prefix = container.getAttribute('data-prefix') || '';
    if (!prefix || prefix.indexOf('__prefix__') !== -1) {
      var rawId = (container.id || '').replace(/^container-id_/, '');
      var idParts = rawId.split('-');
      if (idParts.length > 1 && rawId.indexOf('__prefix__') === -1) {
        prefix = idParts.slice(0, -1).join('-') + '-' + type;
      } else {
        var panel = button.closest('.inline-related');
        if (panel) {
          var panelMatch = (panel.id || '').match(/^(.+-\d+)$/);
          if (panelMatch) {
            prefix = panelMatch[1] + '-' + type;
          } else {
            var namedField = panel.querySelector('input[name*="-"], select[name*="-"]');
            if (namedField) {
              var fieldMatch = namedField.name.match(/^(.+?-\d+)-/);
              if (fieldMatch) {
                prefix = fieldMatch[1] + '-' + type;
              }
            }
          }
        }
      }
      if (!prefix || prefix.indexOf('__prefix__') !== -1) {
        prefix = type;
      }
      container.setAttribute('data-prefix', prefix);
    }
    if (container.id) {
      button.setAttribute('data-container', container.id);
    }
    return { container: container, prefix: prefix };
  }

  // ── Dynamic rows: add choice ──
  document.addEventListener('click', function(event){
    var addButton = event.target.closest('.dyn-add-choice-btn');
    if(!addButton) return;
    event.preventDefault();
    var containerInfo = getContainerAndPrefix(addButton, 'choice');
    var container = containerInfo.container;
    var prefix = containerInfo.prefix;
    if(!container) return;
    var nextIndex = getNextIndex(container);
    var rowElement = document.createElement('div');
    rowElement.className = 'dyn-row';
    rowElement.style.cssText = 'display:flex;gap:8px;margin-bottom:4px;align-items:center;';
    rowElement.innerHTML =
      '<input type="text" name="' + prefix + '_label_' + nextIndex + '" placeholder="Choice label" ' +
      'style="flex:1;min-width:200px;" class="choice-label-input">' +
      '<button type="button" class="dyn-remove-btn" ' +
      'style="color:#ba2121;background:none;border:none;font-size:16px;cursor:pointer;font-weight:bold;" ' +
      'title="Remove">\u2715</button>';
    container.appendChild(rowElement);
  });

  // ── Dynamic rows: add error ──
  document.addEventListener('click', function(event){
    var addButton = event.target.closest('.dyn-add-error-btn');
    if(!addButton) return;
    event.preventDefault();
    var containerInfo = getContainerAndPrefix(addButton, 'error');
    var container = containerInfo.container;
    var prefix = containerInfo.prefix;
    if(!container) return;
    var nextIndex = getNextIndex(container);
    var rowElement = document.createElement('div');
    rowElement.className = 'dyn-row';
    rowElement.style.cssText = 'display:flex;gap:8px;margin-bottom:4px;align-items:center;';
    rowElement.innerHTML =
      '<input type="text" name="' + prefix + '_key_' + nextIndex + '" placeholder="key (e.g. required)" style="width:140px;">' +
      '<input type="text" name="' + prefix + '_label_' + nextIndex + '" placeholder="Error text (English)" style="flex:1;min-width:200px;">' +
      '<button type="button" class="dyn-remove-btn" ' +
      'style="color:#ba2121;background:none;border:none;font-size:16px;cursor:pointer;font-weight:bold;" ' +
      'title="Remove">\u2715</button>';
    container.appendChild(rowElement);
  });

  // ── Dynamic rows: remove ──
  document.addEventListener('click', function(event){
    var removeButton = event.target.closest('.dyn-remove-btn');
    if(!removeButton) return;
    event.preventDefault();
    var rowElement = removeButton.closest('.dyn-row');
    var parentPanel = removeButton.closest('.inline-related');
    if(rowElement) rowElement.remove();
    checkDuplicateLabels(parentPanel);
  });

  // ── Duplicate label detection ──
  function checkDuplicateLabels(panel){
    if(!panel) return false;
    var addButton = panel.querySelector('.dyn-add-choice-btn');
    if(!addButton) return false;
    var previousError = addButton.parentElement.querySelector('.dup-error-banner');
    if(previousError) previousError.remove();
    var labelInputs = panel.querySelectorAll('.choice-label-input');
    labelInputs.forEach(function(inputElement){ inputElement.style.borderColor = ''; });

    var seenLabels = {};
    var duplicateLabels = [];
    labelInputs.forEach(function(inputElement){
      var normalizedValue = inputElement.value.trim().toLowerCase();
      if(!normalizedValue) return;
      if(seenLabels[normalizedValue]){
        duplicateLabels.push(seenLabels[normalizedValue].value.trim());
        inputElement.style.borderColor = '#ba2121';
        seenLabels[normalizedValue].style.borderColor = '#ba2121';
      } else {
        seenLabels[normalizedValue] = inputElement;
      }
    });

    if(duplicateLabels.length > 0){
      var errorBanner = document.createElement('div');
      errorBanner.className = 'dup-error-banner';
      errorBanner.style.cssText = 'color:#ba2121;font-size:12px;margin-top:4px;margin-bottom:4px;';
      errorBanner.textContent = 'Duplicate labels found: ' + [...new Set(duplicateLabels)].join(', ') + '. Labels must be unique.';
      addButton.parentElement.insertBefore(errorBanner, addButton);
      return true;
    }
    return false;
  }

  document.addEventListener('input', function(event){
    if(!event.target.classList.contains('choice-label-input')) return;
    checkDuplicateLabels(event.target.closest('.inline-related'));
  });

  // ── Visibility toggles ──
  var VALIDATION_FIELDS = ['validate_method', 'validation_type', 'render_as',
                           'errors_field', 'min_choices', 'max_choices', 'choices_field'];
  var MC_FIELDS = ['min_choices', 'max_choices', 'choices_field'];

  function initToggles(){
    document.querySelectorAll('.inline-related').forEach(function(panel){
      var operationTypeSelect = panel.querySelector('select[name$="-operation_type"]');
      var validationTypeSelect = panel.querySelector('select[name$="-validation_type"]');
      if(!operationTypeSelect) return;

      var validationRows = findFieldRows(panel, VALIDATION_FIELDS);

      function updateFieldVisibility(){
        var isNonLlm = operationTypeSelect.value === 'non_llm';
        var isMultipleChoice = validationTypeSelect && validationTypeSelect.value === 'MULTIPLE_CHOICE';
        validationRows.forEach(function(fieldRow){
          var isMultipleChoiceRow = false;
          for(var fieldIndex = 0; fieldIndex < MC_FIELDS.length; fieldIndex++){
            if(fieldRow.classList.contains('field-' + MC_FIELDS[fieldIndex])){
              isMultipleChoiceRow = true;
              break;
            }
          }
          fieldRow.style.display = (isMultipleChoiceRow ? (isNonLlm && isMultipleChoice) : isNonLlm) ? '' : 'none';
        });
      }

      updateFieldVisibility();
      if(!operationTypeSelect.dataset.tb){
        operationTypeSelect.dataset.tb = '1';
        operationTypeSelect.addEventListener('change', updateFieldVisibility);
      }
      if(validationTypeSelect && !validationTypeSelect.dataset.tb){
        validationTypeSelect.dataset.tb = '1';
        validationTypeSelect.addEventListener('change', updateFieldVisibility);
      }

      // ── Real-time min/max validation ──
      var minChoicesInput = panel.querySelector('input[name$="-min_choices"]');
      var maxChoicesInput = panel.querySelector('input[name$="-max_choices"]');
      if(minChoicesInput && maxChoicesInput && !minChoicesInput.dataset.vb){
        minChoicesInput.dataset.vb = '1';
        function validateMinMaxChoices(){
          var minVal = parseInt(minChoicesInput.value, 10);
          var maxVal = parseInt(maxChoicesInput.value, 10);
          var errorElementId = maxChoicesInput.id + '_mmerr';
          var existingError = document.getElementById(errorElementId);
          if(existingError) existingError.remove();
          if(!isNaN(minVal) && !isNaN(maxVal) && maxVal < minVal){
            var errorMessageElement = document.createElement('div');
            errorMessageElement.id = errorElementId;
            errorMessageElement.style.cssText = 'color:#ba2121;font-size:12px;margin-top:2px;';
            errorMessageElement.textContent = 'Max choices must be \u2265 min choices.';
            maxChoicesInput.parentElement.appendChild(errorMessageElement);
            maxChoicesInput.style.borderColor = '#ba2121';
          } else {
            maxChoicesInput.style.borderColor = '';
          }
        }
        minChoicesInput.addEventListener('input', validateMinMaxChoices);
        maxChoicesInput.addEventListener('input', validateMinMaxChoices);
      }
    });
  }

  // ── Prevent form submit if duplicate labels ──
  document.addEventListener('submit', function(event){
    var formElement = event.target;
    var inlinePanels = formElement.querySelectorAll('.inline-related');
    var isBlocked = false;
    inlinePanels.forEach(function(inlinePanel){
      if(checkDuplicateLabels(inlinePanel)) isBlocked = true;
    });
    if(isBlocked){
      event.preventDefault();
      alert('Please fix duplicate choice labels before saving.');
    }
  });

  function addActionHints(){
    document.querySelectorAll('.inline_actions').forEach(function(actionRow){
      if(actionRow.querySelector('.action-hint')) return;
      var hintElement = document.createElement('div');
      hintElement.className = 'action-hint help-block';
      hintElement.textContent = 'Save your changes before generating translations or audio.';
      actionRow.parentElement.insertBefore(hintElement, actionRow.nextSibling);
    });
  }

  // ── Collapsible SM cards ──
  function makeCollapsible(){
    document.querySelectorAll('.inline-related:not(.empty-form)').forEach(function(panel){
      var headerElement = panel.querySelector('.card-header');
      var bodyElement = panel.querySelector('.card-body');
      if(!headerElement || !bodyElement || headerElement.dataset.collapsible) return;
      headerElement.dataset.collapsible = '1';
      headerElement.style.cursor = 'pointer';
      bodyElement.style.display = 'none';
      var arrowElement = document.createElement('span');
      arrowElement.className = 'collapse-arrow';
      arrowElement.style.cssText = 'margin-left:8px;font-size:10px;';
      arrowElement.textContent = '\u25B6';
      var titleElement = headerElement.querySelector('.card-title');
      if(titleElement) titleElement.appendChild(arrowElement);
      headerElement.addEventListener('click', function(event){
        if(event.target.closest('input,a,button')) return;
        var isHidden = bodyElement.style.display === 'none';
        bodyElement.style.display = isHidden ? '' : 'none';
        arrowElement.textContent = isHidden ? '\u25BC' : '\u25B6';
      });
    });
  }

  function init(){
    initToggles();
    addActionHints();
    makeCollapsible();
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  var inlineGroup = document.querySelector('.inline-group');
  if(inlineGroup){
    new MutationObserver(function(){ init(); }).observe(inlineGroup, { childList: true, subtree: false });
  }

  if(window.jQuery){
    window.jQuery(document).on('formset:added', function(){
      init();
    });
  }
})();
