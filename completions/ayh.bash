_ayh_completions() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local cmds="doctor version auth channel calendar quota ai video upload comments captions"
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${cmds}" -- "${cur}") )
        return
    fi
    case "${COMP_WORDS[1]}" in
        auth) COMPREPLY=( $(compgen -W "status login logout" -- "${cur}") ) ;;
        calendar) COMPREPLY=( $(compgen -W "list grid add" -- "${cur}") ) ;;
        quota) COMPREPLY=( $(compgen -W "status" -- "${cur}") ) ;;
        ai) COMPREPLY=( $(compgen -W "title description tags script thumbnail" -- "${cur}") ) ;;
        video) COMPREPLY=( $(compgen -W "info list" -- "${cur}") ) ;;
        upload) COMPREPLY=( $(compgen -W "prepare run" -- "${cur}") ) ;;
        comments) COMPREPLY=( $(compgen -W "list reply" -- "${cur}") ) ;;
        captions) COMPREPLY=( $(compgen -W "list" -- "${cur}") ) ;;
        channel) COMPREPLY=( $(compgen -W "info" -- "${cur}") ) ;;
    esac
}
complete -F _ayh_completions ayh
