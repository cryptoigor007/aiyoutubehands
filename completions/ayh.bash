_ayh_completions() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local cmds="doctor version auth channel calendar quota ai video upload comments captions playlist"
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${cmds}" -- "${cur}") ); return
    fi
    case "${COMP_WORDS[1]}" in
        auth) COMPREPLY=( $(compgen -W "status login logout" -- "$cur") ) ;;
        video) COMPREPLY=( $(compgen -W "info publish schedule delete thumbnail" -- "$cur") ) ;;
        upload) COMPREPLY=( $(compgen -W "prepare run" -- "$cur") ) ;;
        playlist) COMPREPLY=( $(compgen -W "list create add delete" -- "$cur") ) ;;
        comments) COMPREPLY=( $(compgen -W "list reply moderate" -- "$cur") ) ;;
        captions) COMPREPLY=( $(compgen -W "list upload" -- "$cur") ) ;;
        calendar) COMPREPLY=( $(compgen -W "list grid add" -- "$cur") ) ;;
        ai) COMPREPLY=( $(compgen -W "title description tags script thumbnail chapters translate calendar" -- "$cur") ) ;;
        channel) COMPREPLY=( $(compgen -W "info" -- "$cur") ) ;;
        quota) COMPREPLY=( $(compgen -W "status" -- "$cur") ) ;;
    esac
}
complete -F _ayh_completions ayh
